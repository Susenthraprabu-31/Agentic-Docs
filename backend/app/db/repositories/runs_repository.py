import uuid

from datetime import datetime, timezone

from typing import Any, Optional



from app.db.supabase_client import get_memory_store, get_supabase, supabase_call

from app.extraction.schemas import RunStatus





def _now_iso() -> str:

    return datetime.now(timezone.utc).isoformat()





class RunsRepository:

    def create_run(

        self,

        state: str,

        county: str,

        query_type: str,

        query_value: str,

    ) -> dict[str, Any]:

        run_id = str(uuid.uuid4())

        row = {

            "id": run_id,

            "state": state,

            "county": county,

            "query_type": query_type,

            "query_value": query_value,

            "status": RunStatus.PENDING.value,

            "plan_json": None,

            "error_message": None,

            "started_at": None,

            "completed_at": None,

            "created_at": _now_iso(),

        }

        mem = get_memory_store()

        mem.runs[run_id] = row



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("runs").insert(row).execute(),

                label="create_run",

            )

            if result and result.data:

                return result.data[0]

        return row



    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:

        mem = get_memory_store()

        if run_id in mem.runs:

            mem.runs[run_id].update(fields)

        elif run_id not in mem.runs:

            mem.runs[run_id] = {"id": run_id, **fields}



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("runs").update(fields).eq("id", run_id).execute(),

                label="update_run",

            )

            if result and result.data:

                return result.data[0]



        return mem.runs.get(run_id, {})



    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:

        mem_run = get_memory_store().runs.get(run_id)

        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("runs").select("*").eq("id", run_id).execute(),

                label="get_run",

            )

            if result and result.data:

                return result.data[0]

        return mem_run



    def add_event(

        self,

        run_id: str,

        event_type: str,

        source: Optional[str],

        payload: dict[str, Any],

    ) -> dict[str, Any]:

        event_id = str(uuid.uuid4())

        row = {

            "id": event_id,

            "run_id": run_id,

            "event_type": event_type,

            "source": source,

            "payload": payload,

            "created_at": _now_iso(),

        }

        mem = get_memory_store()

        mem.run_events.append(row)



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: client.table("run_events").insert(row).execute(),

                label="add_event",

            )

            if result and result.data:

                return result.data[0]

        return row



    def get_events(self, run_id: str) -> list[dict[str, Any]]:

        mem_events = [e for e in get_memory_store().run_events if e["run_id"] == run_id]



        client = get_supabase()

        if client:

            result = supabase_call(

                lambda: (

                    client.table("run_events")

                    .select("*")

                    .eq("run_id", run_id)

                    .order("created_at")

                    .execute()

                ),

                label="get_events",

            )

            if result and result.data:

                by_id = {e["id"]: e for e in result.data}

                for event in mem_events:

                    by_id[event["id"]] = event

                return sorted(by_id.values(), key=lambda e: e.get("created_at", ""))



        return mem_events


