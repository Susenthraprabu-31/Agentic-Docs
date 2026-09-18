import uuid

from datetime import datetime, timezone

from typing import Any



from app.db.supabase_client import get_memory_store, get_supabase, supabase_call





class RecordsRepository:

    ALLOWED_COLUMNS = {
        "id", "run_id", "source", "apn", "owner_name", "legal_desc",
        "assessed_value", "property_address", "raw_json", "created_at",
    }

    def insert(self, run_id: str, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        # Harmonize legal_desc / legal_description
        legal_val = payload.get("legal_desc") or payload.get("legal_description")

        row = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        if legal_val:
            row["legal_desc"] = legal_val
            row["legal_description"] = legal_val

        mem = get_memory_store()
        mem.records.append(row)

        client = get_supabase()
        if client:
            # Only send valid DB columns to Supabase
            db_row = {k: v for k, v in row.items() if k in self.ALLOWED_COLUMNS}
            result = supabase_call(
                lambda: client.table("records").insert(db_row).execute(),
                label="insert_record",
            )
            if result and result.data:
                res = dict(result.data[0])
                if "legal_desc" in res and "legal_description" not in res:
                    res["legal_description"] = res["legal_desc"]
                return res

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
                by_id = {}
                for r in result.data:
                    item = dict(r)
                    if "legal_desc" in item and "legal_description" not in item:
                        item["legal_description"] = item["legal_desc"]
                    by_id[item["id"]] = item
                for record in mem_records:
                    by_id[record["id"]] = record
                return list(by_id.values())



        return mem_records

    def delete_by_ids(self, run_id: str, ids: list[str]) -> int:
        if not ids:
            return 0

        id_set = set(ids)
        mem = get_memory_store()
        before = len(mem.records)
        mem.records = [
            r for r in mem.records
            if not (r.get("run_id") == run_id and r.get("id") in id_set)
        ]
        removed = before - len(mem.records)

        client = get_supabase()
        if client:
            result = supabase_call(
                lambda: client.table("records").delete().eq("run_id", run_id).in_("id", ids).execute(),
                label="delete_records",
            )
            if result and result.data:
                return len(result.data)

        return removed


