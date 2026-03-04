from pathlib import Path

path = Path("tests/unit/test_tools.py")
content = path.read_text()

# We need to change where monkeypatch looks:
# Instead of patching `tools_module._get_dense_model`, it should patch `tools_module._embedding._get_dense_model`
# Wait, let's just replace `tools_module, "_get_dense_model"` with `habitantes.domain.tools._embedding, "_get_dense_model"`
# First, add import in test_tools.py
if "from habitantes.domain.tools import _embedding, _ranking, search" not in content:
    content = content.replace(
        "import habitantes.domain.tools as tools_module",
        "import habitantes.domain.tools as tools_module\nfrom habitantes.domain.tools import _embedding, _ranking, search",
    )

# Replace patching components
content = content.replace(
    'tools_module, "_get_collection_name"', 'search, "_get_collection_name"'
)
content = content.replace(
    'tools_module, "_collection_name"', 'search, "_collection_name"'
)

content = content.replace(
    'tools_module, "_get_qdrant_client"', 'search, "_get_qdrant_client"'
)
content = content.replace('tools_module, "_qdrant_client"', 'search, "_qdrant_client"')

content = content.replace(
    'tools_module, "_get_dense_model"', '_embedding, "_get_dense_model"'
)
content = content.replace('tools_module, "_dense_model"', '_embedding, "_dense_model"')

content = content.replace('tools_module, "_embed_query"', '_embedding, "_embed_query"')

path.write_text(content)

path_ag = Path("tests/integration/test_agent_flow.py")
c_ag = path_ag.read_text()
if "from habitantes.domain.tools import search" not in c_ag:
    c_ag = c_ag.replace(
        "import habitantes.domain.tools as tools_module",
        "import habitantes.domain.tools as tools_module\nfrom habitantes.domain.tools import search as search_module",
    )
c_ag = c_ag.replace(
    'tools_module, "_get_collection_name"', 'search_module, "_get_collection_name"'
)
c_ag = c_ag.replace(
    'tools_module, "_collection_name"', 'search_module, "_collection_name"'
)
path_ag.write_text(c_ag)

path_c = Path("tests/integration/test_conversations.py")
c_c = path_c.read_text()
if "from habitantes.domain.tools import search" not in c_c:
    c_c = c_c.replace(
        "import habitantes.domain.tools as tools_module",
        "import habitantes.domain.tools as tools_module\nfrom habitantes.domain.tools import search as search_module",
    )
c_c = c_c.replace(
    'tools_module, "_get_collection_name"', 'search_module, "_get_collection_name"'
)
c_c = c_c.replace(
    'tools_module, "_collection_name"', 'search_module, "_collection_name"'
)
path_c.write_text(c_c)
