import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.supabase_client import get_memory_store, get_supabase, supabase_call


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchesRepository:
    """Repository for managing multi-order batches and individual batch order items."""

    def create_batch(
        self,
        name: str,
        total_orders: int,
        workflow_template: str = "recorder_deed",
        concurrency: int = 2,
        custom_graph: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        row: dict[str, Any] = {
            "id": batch_id,
            "name": name or f"Batch {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            "status": "pending",
            "total_orders": total_orders,
            "completed_orders": 0,
            "failed_orders": 0,
            "running_orders": 0,
            "concurrency": max(1, min(concurrency, 6)),
            "workflow_template": workflow_template,
            "custom_graph": custom_graph,
            "created_at": _now_iso(),
            "completed_at": None,
        }

        mem = get_memory_store()
        mem.batches[batch_id] = row

        client = get_supabase()
        if client:
            try:
                client.table("batches").insert(row).execute()
            except Exception:
                pass
        return row

    def get_batch(self, batch_id: str) -> Optional[dict[str, Any]]:
        mem = get_memory_store()
        row = mem.batches.get(batch_id)
        if row:
            return dict(row)

        client = get_supabase()
        if client:
            try:
                res = client.table("batches").select("*").eq("id", batch_id).execute()
                if res and res.data:
                    return res.data[0]
            except Exception:
                pass
        return None

    def update_batch(self, batch_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        mem = get_memory_store()
        if batch_id in mem.batches:
            mem.batches[batch_id].update(fields)
            row = dict(mem.batches[batch_id])
        else:
            row = None

        client = get_supabase()
        if client:
            try:
                client.table("batches").update(fields).eq("id", batch_id).execute()
            except Exception:
                pass
        return row

    def list_batches(self, limit: int = 50) -> list[dict[str, Any]]:
        mem = get_memory_store()
        batches = list(mem.batches.values())
        batches.sort(key=lambda b: b.get("created_at") or "", reverse=True)

        client = get_supabase()
        if client:
            try:
                res = client.table("batches").select("*").order("created_at", desc=True).limit(limit).execute()
                if res and res.data:
                    return res.data
            except Exception:
                pass
        return batches[:limit]

    def add_order(
        self,
        batch_id: str,
        state: str,
        county: str,
        query_type: str,
        query_value: str,
        book_number: Optional[str] = None,
        page_number: Optional[str] = None,
        workflow_template: Optional[str] = None,
        order_index: int = 0,
    ) -> dict[str, Any]:
        order_id = str(uuid.uuid4())
        row: dict[str, Any] = {
            "id": order_id,
            "batch_id": batch_id,
            "order_index": order_index,
            "run_id": None,
            "state": state.upper(),
            "county": county.lower(),
            "query_type": query_type,
            "query_value": query_value,
            "book_number": book_number,
            "page_number": page_number,
            "workflow_template": workflow_template or "recorder_deed",
            "status": "pending",
            "error_message": None,
            "report_id": None,
            "created_at": _now_iso(),
            "completed_at": None,
        }

        mem = get_memory_store()
        mem.batch_orders.append(row)

        client = get_supabase()
        if client:
            try:
                client.table("batch_orders").insert(row).execute()
            except Exception:
                pass
        return row

    def get_orders(self, batch_id: str) -> list[dict[str, Any]]:
        mem = get_memory_store()
        orders = [dict(o) for o in mem.batch_orders if o.get("batch_id") == batch_id]
        orders.sort(key=lambda o: o.get("order_index", 0))

        client = get_supabase()
        if client:
            try:
                res = client.table("batch_orders").select("*").eq("batch_id", batch_id).order("order_index").execute()
                if res and res.data:
                    return res.data
            except Exception:
                pass
        return orders

    def update_order(self, order_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        mem = get_memory_store()
        for o in mem.batch_orders:
            if o.get("id") == order_id:
                o.update(fields)
                row = dict(o)
                break
        else:
            row = None

        client = get_supabase()
        if client:
            try:
                client.table("batch_orders").update(fields).eq("id", order_id).execute()
            except Exception:
                pass
        return row
