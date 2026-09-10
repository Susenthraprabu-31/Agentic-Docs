import uuid

from datetime import datetime, timezone

from typing import Any



from app.db.supabase_client import get_memory_store, get_supabase, supabase_call





class RecordsRepository:

    def insert(self, run_id: str, record: dict[str, Any]) -> dict[str, Any]:

        row = {

            "id": str(uuid.uuid4()),

            "run_id": run_id,

            "created_at": datetime.now(timezone.utc).isoformat(),

            **record,

        }

        mem = get_memory_store()

        mem.records.append(row)



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("records").insert(row).execute(),

                label="insert_record",

            )

            if result and result.data:

                return result.data[0]

        return row



    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:

        mem_records = [r for r in get_memory_store().records if r["run_id"] == run_id]



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("records").select("*").eq("run_id", run_id).execute(),

                label="list_records",

            )

            if result and result.data:

                by_id = {r["id"]: r for r in result.data}

                for record in mem_records:

                    by_id[record["id"]] = record

                return list(by_id.values())



        return mem_records


