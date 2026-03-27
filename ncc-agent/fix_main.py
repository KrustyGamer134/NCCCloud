import asyncio
import logging
import sys


def _ensure_core_import_path(settings, logger) -> None:
    repo_root = str(getattr(settings, "ncc_repo_root", "") or "").strip()
    if repo_root:
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        return

    logger.debug("NCC_REPO_ROOT not set; relying on editable install/environment import path")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger = logging.getLogger("ncc-agent")

    from agent_core.settings import Settings

    settings = Settings()

    if not settings.cluster_root:
        logger.error("CLUSTER_ROOT is not set.")
        sys.exit(1)

    _ensure_core_import_path(settings, logger)

    from agent_core.registration import ensure_registered

    agent_id, api_key = await ensure_registered(settings)
    settings.agent_id = agent_id
    settings.api_key = api_key
    logger.info("Agent %s ready", agent_id)

    from core.admin_api import AdminAPI

    admin_api = AdminAPI.build_default(cluster_root=settings.cluster_root)
    logger.info("AdminAPI initialised")

    from agent_core.connection import AgentConnection
    from agent_core.status_reporter import run_status_reporter

    conn = AgentConnection(settings, admin_api)
    await asyncio.gather(
        conn.connect_loop(),
        run_status_reporter(agent_id, admin_api, lambda: conn.ws),
    )


if __name__ == "__main__":
    asyncio.run(main())
