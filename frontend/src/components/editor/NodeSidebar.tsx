import { DragEvent } from "react";

import { SIDEBAR_NODES, SidebarNodeDef } from "../../lib/nodeCatalog";



const DRAG_TYPE = "application/reactflow";



function onDragStart(event: DragEvent, def: SidebarNodeDef) {

  event.dataTransfer.setData(DRAG_TYPE, def.catalogId);

  event.dataTransfer.effectAllowed = "move";

}



function PipelineItem({ def }: { def: SidebarNodeDef }) {

  return (

    <div

      draggable

      onDragStart={(e) => onDragStart(e, def)}

      className="group cursor-grab active:cursor-grabbing rounded-lg border border-teal-900/50 bg-teal-950/20 px-3 py-2.5 hover:border-teal-600/60 hover:bg-teal-950/40 transition-colors"

    >

      <div className="flex items-center gap-2">

        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-teal-900/40 text-teal-300 text-[10px] font-bold">

          {def.label.slice(0, 2).toUpperCase()}

        </span>

        <div className="min-w-0">

          <p className="text-xs font-medium text-teal-100 truncate">{def.label}</p>

          <p className="text-[10px] text-zinc-500 truncate">{def.description}</p>

        </div>

      </div>

    </div>

  );

}



function AIItem({ def }: { def: SidebarNodeDef }) {

  return (

    <div

      draggable

      onDragStart={(e) => onDragStart(e, def)}

      className="group cursor-grab active:cursor-grabbing rounded-lg border border-violet-900/50 bg-violet-950/20 px-3 py-2.5 hover:border-violet-600/60 hover:bg-violet-950/40 transition-colors"

    >

      <div className="flex items-center gap-2">

        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-violet-900/40 text-violet-300 text-sm">

          ✦

        </span>

        <div className="min-w-0">

          <p className="text-xs font-medium text-violet-100 truncate">{def.label}</p>

          <p className="text-[10px] text-zinc-500 truncate">{def.description}</p>

        </div>

      </div>

    </div>

  );

}



export default function NodeSidebar() {

  const pipelineNodes = SIDEBAR_NODES.filter((n) => n.category === "pipeline");

  const aiNodes = SIDEBAR_NODES.filter((n) => n.category === "ai");



  return (

    <aside className="w-56 shrink-0 border-r border-teal-900/40 bg-[#0c1017] flex flex-col overflow-hidden">

      <div className="px-3 py-3 border-b border-teal-900/40">

        <h2 className="text-xs font-semibold uppercase tracking-wider text-teal-400">Nodes</h2>

        <p className="text-[10px] text-zinc-600 mt-1">Drag onto the canvas</p>

      </div>



      <div className="flex-1 overflow-y-auto p-2 space-y-4">

        <section>

          <h3 className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">

            Pipeline

          </h3>

          <div className="space-y-1.5">

            {pipelineNodes.map((def) => (

              <PipelineItem key={def.catalogId} def={def} />

            ))}

          </div>

        </section>



        <section>

          <h3 className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">

            AI Agents

          </h3>

          <div className="space-y-1.5">

            {aiNodes.map((def) => (

              <AIItem key={def.catalogId} def={def} />

            ))}

          </div>

        </section>

      </div>

    </aside>

  );

}


