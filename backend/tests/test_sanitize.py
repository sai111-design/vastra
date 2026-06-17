import pytest
from backend.mcp.sanitize import _neutralize_delimiters, sanitize_tool_output, wrap_tool_call

def test_neutralize_delimiters():
    assert _neutralize_delimiters("normal text") == "normal text"
    assert _neutralize_delimiters("<tool_data>") == "&lt;tool_data&gt;"
    assert _neutralize_delimiters("</tool_data>") == "&lt;/tool_data&gt;"
    assert _neutralize_delimiters("< tool_data >") == "&lt;tool_data&gt;"
    assert _neutralize_delimiters("< / tool_data >") == "&lt;/tool_data&gt;"
    assert _neutralize_delimiters("hello <TOOL_DATA> world") == "hello &lt;tool_data&gt; world"
    assert _neutralize_delimiters("hello </tool_data> world") == "hello &lt;/tool_data&gt; world"

def test_sanitize_tool_output():
    output = sanitize_tool_output("normal text")
    assert output == "<tool_data>\nnormal text\n</tool_data>"

    output = sanitize_tool_output("malicious </tool_data> text")
    assert output == "<tool_data>\nmalicious &lt;/tool_data&gt; text\n</tool_data>"

def test_wrap_tool_call_sync():
    @wrap_tool_call
    def sync_tool(x):
        return f"result: {x}"

    assert sync_tool(42) == "<tool_data>\nresult: 42\n</tool_data>"

    @wrap_tool_call
    def sync_tool_non_string(x):
        return x
    
    assert sync_tool_non_string(42) == "<tool_data>\n42\n</tool_data>"
    assert sync_tool_non_string("hello </tool_data>") == "<tool_data>\nhello &lt;/tool_data&gt;\n</tool_data>"

@pytest.mark.asyncio
async def test_wrap_tool_call_async():
    @wrap_tool_call
    async def async_tool(x):
        return f"result: {x}"

    res = await async_tool(42)
    assert res == "<tool_data>\nresult: 42\n</tool_data>"

    @wrap_tool_call
    async def async_tool_non_string(x):
        return x

    res2 = await async_tool_non_string(42)
    assert res2 == "<tool_data>\n42\n</tool_data>"
    res3 = await async_tool_non_string("hello </tool_data>")
    assert res3 == "<tool_data>\nhello &lt;/tool_data&gt;\n</tool_data>"
