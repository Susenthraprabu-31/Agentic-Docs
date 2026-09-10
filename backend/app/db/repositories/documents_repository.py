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

        mem_docs = [d for d in get_memory_store().documents if d["run_id"] == run_id]



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("documents").select("*").eq("run_id", run_id).execute(),

                label="list_documents",

            )

            if result and result.data:

                by_id = {d["id"]: d for d in result.data}

                for doc in mem_docs:

                    by_id[doc["id"]] = doc

                return list(by_id.values())



        return mem_docs


