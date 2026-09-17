"""Declarative pipeline graph — sequential step1 → step2 → step3 wiring."""

from __future__ import annotations



import logging



from app.drivers.netronline.netronline_driver import NetronlineDriver

from app.pipeline.base_node import BaseNode, PipelineContext

from app.pipeline.nodes.assessor_node import AssessorNode

from app.pipeline.nodes.gis_node import GISNode

from app.pipeline.nodes.input_node import InputNode

from app.pipeline.nodes.netr_resolver_node import NETRResolverNode

from app.pipeline.nodes.normalizer_node import NormalizerNode

from app.pipeline.nodes.output_node import OutputNode

from app.pipeline.nodes.platform_detector_node import PlatformDetectorNode

from app.pipeline.nodes.recorder_node import RecorderNode

from app.pipeline.nodes.report_node import ReportNode

from app.pipeline.nodes.tax_node import TaxNode



logger = logging.getLogger(__name__)





class GraphStep:

    """One executable step in the pipeline graph."""



    async def execute(self, ctx: PipelineContext, netr_driver: NetronlineDriver) -> PipelineContext:

        raise NotImplementedError





class NodeStep(GraphStep):

    def __init__(self, node: BaseNode) -> None:

        self.node = node



    async def execute(self, ctx: PipelineContext, netr_driver: NetronlineDriver) -> PipelineContext:

        return await self.node._safe_run(ctx)





class ConditionalStep(GraphStep):

    def __init__(self, step: GraphStep, predicate, skip_label: str = "skipped") -> None:

        self.step = step

        self.predicate = predicate

        self.skip_label = skip_label



    async def execute(self, ctx: PipelineContext, netr_driver: NetronlineDriver) -> PipelineContext:

        if not self.predicate(ctx):

            logger.info("ConditionalStep: %s — skipped", self.skip_label)

            return ctx

        return await self.step.execute(ctx, netr_driver)





def build_pipeline_graph(netr_driver: NetronlineDriver) -> list[GraphStep]:

    """Return ordered sequential graph steps (no parallel groups)."""

    return [

        NodeStep(InputNode()),

        NodeStep(NETRResolverNode(netr_driver)),

        NodeStep(PlatformDetectorNode()),

        NodeStep(AssessorNode(netr_driver)),

        NodeStep(RecorderNode(netr_driver)),

        NodeStep(GISNode(netr_driver)),

        ConditionalStep(

            NodeStep(TaxNode(netr_driver)),

            predicate=lambda c: bool(c.tax_url),

            skip_label="TaxNode (no tax_url)",

        ),

        NodeStep(NormalizerNode()),

        NodeStep(ReportNode()),

        NodeStep(OutputNode()),

    ]





async def execute_graph(

    steps: list[GraphStep],

    ctx: PipelineContext,

    netr_driver: NetronlineDriver,

) -> PipelineContext:

    for step in steps:

        ctx = await step.execute(ctx, netr_driver)

    return ctx


