import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(wt):
    p = StdioServerParameters(
        command="/workspace/dbt-factory/.venv/bin/python",
        args=["/workspace/dbt-factory/backend/mcp_server.py"],
        env={"DBT_PROJECT_DIR": wt, "PATH": "/workspace/dbt-factory/.venv/bin:/usr/bin:/bin"},
    )
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        names = [t.name for t in tools.tools]
        res = await s.call_tool("dbt_lineage", {"name": "orders", "direction": "upstream"})
        lin = json.loads(res.content[0].text)
        res = await s.call_tool("data_query", {"sql": "delete from {{ ref('orders') }}"})
        blocked = json.loads(res.content[0].text)
        return names, lin, blocked


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(sys.argv[1])), default=str)[:1500])
