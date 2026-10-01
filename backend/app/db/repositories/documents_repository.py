import uuid

from datetime import datetime, timezone

from typing import Any



from app.db.supabase_client import get_memory_store, get_supabase, supabase_call





class DocumentsRepository:

    def insert(self, run_id: str, document: dict[str, Any]) -> dict[str, Any]:

        row = {

            "id": str(uuid.uuid4()),

            "run_id": run_id,

            "created_at": datetime.now(timezone.utc).isoformat(),

            **document,

        }

        mem = get_memory_store()

        mem.documents.append(row)



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("documents").insert(row).execute(),

                label="insert_document",

            )

            if result and result.data:

                return result.data[0]

        return row



    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        mem_docs = [d for d in get_memory_store().documents if d.get("run_id") == run_id]

        client = get_supabase()
        if client:
            result = supabase_call(
                lambda: client.table("documents").select("*").eq("run_id", run_id).execute(),
                label="list_documents",
            )
            if result and result.data:
                by_id = {d["id"]: dict(d) for d in result.data}
                for doc in mem_docs:
                    doc_id = doc.get("id")
                    if doc_id not in by_id:
                        by_id[doc_id] = doc
                    else:
                        existing = by_id[doc_id]
                        for k, v in doc.items():
                            if v and not existing.get(k):
                                existing[k] = v
                return list(by_id.values())

        return mem_docs

    def get_by_id(self, doc_id: str) -> dict[str, Any] | None:
        mem = get_memory_store()
        doc = next((d for d in mem.documents if d.get("id") == doc_id), None)
        if doc:
            return doc

        client = get_supabase()
        if client:
            result = supabase_call(
                lambda: client.table("documents").select("*").eq("id", doc_id).execute(),
                label="get_document",
            )
            if result and result.data:
                return result.data[0]
        return None

    def update(self, doc_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        if not updates:
            return self.get_by_id(doc_id)

        mem = get_memory_store()
        updated: dict[str, Any] | None = None
        for index, doc in enumerate(mem.documents):
            if doc.get("id") == doc_id:
                merged = {**doc, **updates}
                mem.documents[index] = merged
                updated = merged
                break

        client = get_supabase()
        if client:
            result = supabase_call(
                lambda: client.table("documents").update(updates).eq("id", doc_id).execute(),
                label="update_document",
            )
            if result and result.data:
                return result.data[0]

        return updated or self.get_by_id(doc_id)

    def delete_by_ids(self, run_id: str, ids: list[str]) -> int:
        if not ids:
            return 0

        id_set = set(ids)
        mem = get_memory_store()
        before = len(mem.documents)
        mem.documents = [
            d for d in mem.documents
            if not (d.get("run_id") == run_id and d.get("id") in id_set)
        ]
        removed = before - len(mem.documents)

        client = get_supabase()
        if client:
            result = supabase_call(
                lambda: client.table("documents").delete().eq("run_id", run_id).in_("id", ids).execute(),
                label="delete_documents",
            )
            if result and result.data:
                return len(result.data)

        return removed


