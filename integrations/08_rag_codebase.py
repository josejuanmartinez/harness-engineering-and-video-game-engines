"""
EXERCISE 08: hybrid RAG over code
Time: 60 min
Stack: rank-bm25, OpenAI Embeddings API, NumPy, Anthropic SDK
The Anthropic API has no embeddings endpoint, which is why providers are mixed here.

TASK
Index ../c and answer questions like "which exercises deal with memory ordering?"
with file and line citations. If you have a real C++ library at hand, use it as the
corpus: it will be more realistic.

REQUIREMENTS
- Structure-aware chunking: comments and functions, not every N characters
- Keep metadata on each chunk: file, lines, symbol
- BM25 search and embedding search with cosine similarity in NumPy
- Merge both with Reciprocal Rank Fusion
- Rerank the top 20 with claude-haiku-5-5
- Answer citing file:line; if there isn't enough context, say so
- Save the index to disk and reindex only what changed (file hash)

EVALUATE IT
- Write 10 questions with the correct file as the answer
- Measure recall@5 with BM25, with embeddings and with the hybrid, and compare them
- Try exact identifiers: that's where BM25 usually wins

GOING FURTHER
- Compare with giving the agent only grep and read_file. Which wins, and at what cost?
- Add contextual retrieval: a summary of the file in front of each chunk

QUESTIONS YOU MIGHT GET
- Why is code a worse fit than prose for pure embeddings?
- How do you keep the index fresh with continuous commits?
- How do you apply per-file permissions in search?
- When do you not need RAG at all?

USAGE
  python integrations/08_rag_codebase.py index              # (re)index what changed
  python integrations/08_rag_codebase.py ask "question"     # answer with citations
  python integrations/08_rag_codebase.py eval [--rerank]    # recall@5 per method
  Add --contextual to prepend the file header to each chunk.
  No arguments: eval + a sample question.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import tree_sitter_cpp as tscpp
from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from tree_sitter import Language, Parser

load_dotenv()

REPO = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO / "c"
INDEX_PATH = REPO / "integrations" / "data" / "rag_index.json"

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
RERANK_MODEL = "claude-haiku-5-5"
ANSWER_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-opus-5-5"

RRF_K = 60
RERANK_TOP = 20
ANSWER_TOP = 8
CONTEXT_CHARS = 600   # how much of the file header is prepended in contextual mode


# ---------------------------------------------------------------------------
# Structure-based chunking with tree-sitter
# ---------------------------------------------------------------------------

PARSER = Parser(Language(tscpp.language()))
UNITS = {"function_definition", "class_specifier", "struct_specifier",
         "enum_specifier", "union_specifier"}
MAX_LINES = 80  # longer classes are split by method


def symbol_of(node, src):
    n = node.child_by_field_name("name")
    if n is None:  # functions: the name is nested in declarator(s)
        d = node.child_by_field_name("declarator")
        while d is not None and d.child_by_field_name("declarator") is not None:
            d = d.child_by_field_name("declarator")
        n = d
    return src[n.start_byte:n.end_byte].decode() if n else "<anon>"


def unwrap(node):
    """`struct X {...};` and `template<...> ...` wrap the real unit."""
    if node.type in ("declaration", "field_declaration"):
        t = node.child_by_field_name("type")
        if t is not None and t.type in UNITS and t.child_by_field_name("body"):
            return t
    if node.type == "template_declaration":
        for c in node.named_children:
            if c.type in UNITS or c.type == "declaration":
                return unwrap(c) or c
    return node if node.type in UNITS else None


def chunk_source(src: bytes, rel_path: str) -> list[dict]:
    tree = PARSER.parse(src)
    chunks, pending = [], []

    def emit(start, end, kind, symbol):
        text = src[start.start_byte:end.end_byte].decode("utf-8", errors="replace")
        if text.strip():
            chunks.append({
                "file": rel_path,
                "start_line": start.start_point[0] + 1,
                "end_line": end.end_point[0] + 1,
                "kind": kind,
                "symbol": symbol,
                "text": text,
            })

    def flush():
        nonlocal pending
        if pending:
            emit(pending[0], pending[-1], "comment", None)
            pending = []

    def walk(parent, scope=""):
        nonlocal pending
        for node in parent.named_children:
            if node.type == "comment":
                # comment separated from the previous one by a blank line -> new block
                if pending and node.start_point[0] > pending[-1].end_point[0] + 1:
                    flush()
                pending.append(node)
                continue
            if node.type == "namespace_definition":
                flush()
                body = node.child_by_field_name("body")
                if body:
                    walk(body, scope + symbol_of(node, src) + "::")
                continue
            unit = unwrap(node)
            if unit is None:          # #include, using, etc.
                flush()
                continue
            # is the pending comment attached to this unit?
            glued = pending and node.start_point[0] <= pending[-1].end_point[0] + 1
            start = pending[0] if glued else node
            if glued:
                pending = []
            else:
                flush()
            name = scope + symbol_of(unit, src)
            body = unit.child_by_field_name("body")
            n_lines = node.end_point[0] - start.start_point[0] + 1
            if unit.type != "function_definition" and body and n_lines > MAX_LINES:
                emit(start, body.children[0], unit.type, name)  # header up to "{"
                walk(body, name + "::")                          # one chunk per method
            else:
                emit(start, node, unit.type, name)
        flush()

    walk(tree.root_node)
    return chunks


# ---------------------------------------------------------------------------
# Tokenization for BM25
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    tokens = []
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text):
        tokens.append(word.lower())                     # full identifier: "swap_ints"
        parts = re.split(r"_+", word)                   # snake_case -> swap, ints
        parts = [p for part in parts
                 for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", part)]  # camelCase
        if len(parts) > 1:
            tokens.extend(p.lower() for p in parts)
    return tokens


# ---------------------------------------------------------------------------
# On-disk index with incremental reindexing by file hash
# ---------------------------------------------------------------------------

def searchable_text(chunk: dict, file_header: str | None) -> str:
    """What BM25 and the embeddings see: metadata + (optional) header + code."""
    head = f"// file: {chunk['file']}"
    if chunk["symbol"]:
        head += f" | symbol: {chunk['symbol']}"
    parts = [head]
    if file_header and chunk["kind"] != "comment":
        parts.append("// file context:\n" + file_header[:CONTEXT_CHARS])
    parts.append(chunk["text"])
    return "\n".join(parts)


def embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    vectors = []
    for i in range(0, len(texts), 100):
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts[i:i + 100])
        vectors.extend(d.embedding for d in resp.data)
    return np.array(vectors, dtype=np.float32)


def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"meta": {}, "files": {}}


def build_index(contextual: bool = False, verbose: bool = True) -> dict:
    index = load_index()
    meta = {"embedding_model": EMBEDDING_MODEL, "contextual": contextual}
    if index.get("meta") != meta:
        # changing model or mode invalidates every vector
        index = {"meta": meta, "files": {}}

    current = {}
    for path in sorted(CORPUS_DIR.rglob("*.cpp")):
        rel = path.relative_to(REPO).as_posix()
        src = path.read_bytes()
        current[rel] = (src, hashlib.sha256(src).hexdigest())

    removed = [f for f in index["files"] if f not in current]
    for f in removed:
        del index["files"][f]

    changed = [f for f, (_, h) in current.items()
               if index["files"].get(f, {}).get("hash") != h]

    if changed:
        new_chunks: list[tuple[str, dict]] = []
        for rel in changed:
            src, h = current[rel]
            chunks = chunk_source(src, rel)
            header = next((c["text"] for c in chunks if c["kind"] == "comment"), None)
            for c in chunks:
                c["search_text"] = searchable_text(c, header if contextual else None)
            index["files"][rel] = {"hash": h, "chunks": chunks}
            new_chunks.extend((rel, c) for c in chunks)

        vectors = embed(OpenAI(), [c["search_text"] for _, c in new_chunks])
        for (_, c), v in zip(new_chunks, vectors):
            c["embedding"] = [round(float(x), 6) for x in v]

    if changed or removed:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    if verbose:
        n = sum(len(f["chunks"]) for f in index["files"].values())
        print(f"Index: {len(current)} files, {n} chunks | "
              f"reindexed {len(changed)}, removed {len(removed)} -> {INDEX_PATH.name}")
    return index


# ---------------------------------------------------------------------------
# Search: BM25, embeddings, RRF and reranking
# ---------------------------------------------------------------------------

class RetrievalIndex:
    def __init__(self, index: dict):
        self.chunks = [c for f in index["files"].values() for c in f["chunks"]]
        self.bm25 = BM25Okapi([tokenize(c["search_text"]) for c in self.chunks])
        E = np.array([c["embedding"] for c in self.chunks], dtype=np.float32)
        self.E = E / np.linalg.norm(E, axis=1, keepdims=True)
        self.openai = OpenAI()
        self._query_cache: dict[str, np.ndarray] = {}

    def bm25_ranking(self, query: str) -> list[int]:
        scores = self.bm25.get_scores(tokenize(query))
        return [int(i) for i in np.argsort(-scores) if scores[i] > 0]

    def embedding_ranking(self, query: str) -> list[int]:
        if query not in self._query_cache:
            q = embed(self.openai, [query])[0]
            self._query_cache[query] = q / np.linalg.norm(q)
        sims = self.E @ self._query_cache[query]       # cosine: vectors already normalized
        return [int(i) for i in np.argsort(-sims)]

    def hybrid_ranking(self, query: str) -> list[int]:
        return rrf([self.bm25_ranking(query), self.embedding_ranking(query)])


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for pos, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return sorted(fused, key=fused.get, reverse=True)


class ChunkScore(BaseModel):
    id: int = Field(..., description="fragment id")
    relevance: int = Field(..., ge=0, le=10, description="0 = irrelevant, 10 = answers it directly")


class Reranking(BaseModel):
    scores: list[ChunkScore]


RERANK_PROMPT = """Score from 0 to 10 how much each code fragment helps answer the question.
Return one score per id.

Question: {query}

{fragments}"""


def rerank(ri: RetrievalIndex, query: str, candidates: list[int],
           client: Anthropic) -> list[int]:
    candidates = candidates[:RERANK_TOP]
    fragments = "\n\n".join(
        f"<fragment id=\"{n}\" file=\"{ri.chunks[i]['file']}:{ri.chunks[i]['start_line']}\">\n"
        f"{ri.chunks[i]['text'][:1500]}\n</fragment>"
        for n, i in enumerate(candidates))
    try:
        resp = client.messages.parse(
            model=RERANK_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": RERANK_PROMPT.format(query=query, fragments=fragments)}],
            output_format=Reranking,
        )
        if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
            return candidates
        scores = {s.id: s.relevance for s in resp.parsed_output.scores}
    except (RateLimitError, APIStatusError, APIConnectionError) as e:
        print(f"[rerank] API error, using RRF order: {e}", file=sys.stderr)
        return candidates
    # sorted is stable: ties keep the RRF order
    order = sorted(range(len(candidates)), key=lambda n: -scores.get(n, 0))
    return [candidates[n] for n in order]


# ---------------------------------------------------------------------------
# Answer with citations
# ---------------------------------------------------------------------------

ANSWER_SYSTEM = """You answer questions about a repository of C++ exercises using ONLY the
code fragments you are given. Rules:
- Cite every claim with its source in `file:line` format (e.g. `c/13_game_loop.cpp:11`).
- Don't make up files, lines or symbols that don't appear in the fragments.
- If the fragments aren't enough to answer, say so explicitly: "I don't have enough context
  in the indexed code to answer this" and explain what is missing.
- Answer in English, concisely."""


def answer(ri: RetrievalIndex, query: str) -> str:
    claude = Anthropic()
    top = rerank(ri, query, ri.hybrid_ranking(query), claude)[:ANSWER_TOP]
    context = "\n\n".join(
        f"<fragment file=\"{c['file']}\" lines=\"{c['start_line']}-{c['end_line']}\" "
        f"symbol=\"{c['symbol'] or ''}\">\n{numbered(c)}\n</fragment>"
        for c in (ri.chunks[i] for i in top))
    resp = claude.messages.create(
        model=ANSWER_MODEL,
        max_tokens=1500,
        system=ANSWER_SYSTEM,
        messages=[{"role": "user", "content": f"{context}\n\nQuestion: {query}"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def numbered(chunk: dict) -> str:
    """Number the lines so the model can cite the exact line."""
    return "\n".join(f"{chunk['start_line'] + n:>4} | {line}"
                     for n, line in enumerate(chunk["text"].splitlines()))


# ---------------------------------------------------------------------------
# Evaluation: file-level recall@5
# ---------------------------------------------------------------------------

# The correct answer is the file name; both the exercise and its solution count.
EVAL_SET = [
    # conceptual (no exact vocabulary shared with the code)
    ("Which exercises deal with memory ordering?", {"15_threads_and_atomics.cpp", "03_ring_buffer.cpp", "11_job_system.cpp"}),
    ("Where is traversing a matrix by rows compared with by columns?", {"16_cache_and_data.cpp"}),
    ("Simulation with a fixed time step and interpolation when rendering", {"13_game_loop.cpp"}),
    ("How to avoid dangling pointers when reusing array slots?", {"07_generational_handles.cpp"}),
    ("Blocking queue between threads that waits until there are items", {"10_thread_safe_queue.cpp"}),
    ("Broad-phase collision detection by splitting space into cells", {"12_spatial_hash.cpp"}),
    ("Fixed-size block allocator with a free list", {"06_pool_allocator.cpp"}),
    ("Move constructor and move assignment, rule of five", {"08_move_rule_of_5.cpp", "01_unique_ptr.cpp"}),
    # exact identifiers (where BM25 usually wins)
    ("align_up", {"14_memory_and_alignment.cpp"}),
    ("measure_ms", {"16_cache_and_data.cpp"}),
    ("parse_int", {"13_optional_variant_span.cpp"}),
    ("count_with_atomic", {"15_threads_and_atomics.cpp"}),
]


def top_files(ri: RetrievalIndex, ranking: list[int], k: int = 5) -> list[str]:
    return [Path(ri.chunks[i]["file"]).name for i in ranking[:k]]


def evaluate(ri: RetrievalIndex, with_rerank: bool = False) -> None:
    methods = {
        "bm25": ri.bm25_ranking,
        "embeddings": ri.embedding_ranking,
        "hybrid (RRF)": ri.hybrid_ranking,
    }
    if with_rerank:
        claude = Anthropic()
        methods["hybrid + rerank"] = lambda q: rerank(ri, q, ri.hybrid_ranking(q), claude)

    hits = {m: [] for m in methods}
    for query, expected in EVAL_SET:
        for name, fn in methods.items():
            hits[name].append(bool(expected & set(top_files(ri, fn(query)))))

    width = 62
    header = f"{'question':<{width}} " + " ".join(f"{m:>15}" for m in methods)
    print("\n" + header + "\n" + "-" * len(header))
    for n, (query, _) in enumerate(EVAL_SET):
        q = query if len(query) <= width else query[:width - 1] + "…"
        print(f"{q:<{width}} " + " ".join(f"{'✓' if hits[m][n] else '✗':>15}" for m in methods))
    print("-" * len(header))
    print(f"{'recall@5':<{width}} " + " ".join(f"{np.mean(hits[m]):>15.2f}" for m in methods))

    exact = [n for n, (q, _) in enumerate(EVAL_SET) if " " not in q]
    print(f"{'  exact identifiers only':<{width}} "
          + " ".join(f"{np.mean([hits[m][n] for n in exact]):>15.2f}" for m in methods))
    print(f"{'  conceptual only':<{width}} "
          + " ".join(f"{np.mean([hits[m][n] for n in range(len(EVAL_SET)) if n not in exact]):>15.2f}"
                     for m in methods))


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid RAG over ../c")
    parser.add_argument("command", nargs="?", choices=["index", "ask", "eval"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--rerank", action="store_true", help="include Haiku rerank in eval")
    parser.add_argument("--contextual", action="store_true",
                        help="prepend the file header to each chunk (reindexes everything)")
    args = parser.parse_args()

    index = build_index(contextual=args.contextual)
    if args.command == "index":
        return
    ri = RetrievalIndex(index)

    if args.command == "ask":
        if not args.query:
            parser.error("ask needs a question")
        print(answer(ri, args.query))
    elif args.command == "eval":
        evaluate(ri, with_rerank=args.rerank)
    else:
        evaluate(ri)
        query = "Which exercises deal with memory ordering?"
        print(f"\n> {query}\n")
        print(answer(ri, query))


if __name__ == "__main__":
    main()
