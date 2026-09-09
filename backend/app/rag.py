import chromadb

SPRING_KNOWLEDGE = [
    {
        "id": "n-plus-one",
        "text": "N+1 Query Problem: Occurs when a loop triggers one database query per iteration instead of a single batched query. In Spring Data JPA this often happens when iterating over a @OneToMany or @ManyToMany relationship without using JOIN FETCH or @EntityGraph. Fix: use JOIN FETCH in JPQL, @EntityGraph, or batch fetching."
    },
    {
        "id": "transactional-boundary",
        "text": "Incorrect @Transactional boundaries: Placing @Transactional on a private method has no effect because Spring proxies only intercept public method calls. Also, catching exceptions inside a transactional method can silently prevent rollback. Fix: apply @Transactional to public methods and use rollbackFor to control rollback behavior explicitly."
    },
    {
        "id": "sql-injection",
        "text": "SQL Injection risk: Building SQL or JPQL queries with string concatenation of user input allows injection attacks. Fix: always use parameterized queries with @Param, PreparedStatement, or JPA criteria API instead of concatenating raw strings."
    },
    {
        "id": "missing-security-annotation",
        "text": "Missing security annotations: Controller or service methods that modify sensitive data without @PreAuthorize, @Secured, or equivalent checks can be called by unauthorized users if security config does not restrict the endpoint elsewhere. Fix: add explicit method-level security annotations for sensitive operations."
    },
    {
        "id": "exception-swallowing",
        "text": "Exception swallowing: Catching a broad Exception and doing nothing, or only logging it, hides real failures, especially around database or external service calls. Fix: catch specific exceptions, rethrow or wrap in a custom exception, and ensure calling code can react appropriately."
    },
    {
        "id": "field-injection",
        "text": "Field injection anti-pattern: Using @Autowired directly on fields makes classes harder to test and hides mandatory dependencies. Fix: use constructor injection, which also enables marking fields final and makes dependencies explicit."
    },
    {
        "id": "unbounded-collection-return",
        "text": "Returning unbounded collections from repository methods, such as findAll() on a large table, risks memory exhaustion and slow responses. Fix: use Pageable and Spring Data's paging support for endpoints that could return large result sets."
    },
    {
        "id": "hardcoded-secrets",
        "text": "Hardcoded secrets: Embedding API keys, passwords, or JWT signing secrets directly in source code, even in application.properties committed to git, is an OWASP Top 10 risk. Fix: externalize secrets via environment variables or a secrets manager."
    },
]

_client = chromadb.Client()
_collection = None


def get_collection():
    global _collection
    if _collection is not None:
        return _collection

    _collection = _client.get_or_create_collection(name="spring_knowledge")

    if _collection.count() == 0:
        _collection.add(
            ids=[doc["id"] for doc in SPRING_KNOWLEDGE],
            documents=[doc["text"] for doc in SPRING_KNOWLEDGE],
        )

    return _collection


def retrieve_context(query: str, k: int = 3) -> str:
    collection = get_collection()
    results = collection.query(query_texts=[query], n_results=k)
    docs = results.get("documents", [[]])[0]
    return "\n\n".join(docs)