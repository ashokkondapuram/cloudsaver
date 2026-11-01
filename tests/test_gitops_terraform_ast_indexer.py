from app.gitops_terraform_ast_indexer import index_terraform_file, iter_hcl_resource_blocks


SUB = "00000000-0000-0000-0000-000000000001"


def test_iter_hcl_resource_blocks_finds_vm():
    source = '''
resource "azurerm_linux_virtual_machine" "api" {
  name                = "api-node-01"
  resource_group_name = "prod-rg"
  location            = "eastus"
  size                = "Standard_D4s_v5"
}
'''
    blocks = iter_hcl_resource_blocks(source)
    assert len(blocks) == 1
    assert blocks[0].resource_type == "azurerm_linux_virtual_machine"


def test_index_terraform_file_builds_arm_id():
    source = '''
resource "azurerm_linux_virtual_machine" "api" {
  name                = "api-node-01"
  resource_group_name = "prod-rg"
}
'''
    rows = index_terraform_file(
        file_path="compute.tf",
        source=source,
        scope=dict(azure_subscription_id=SUB),
    )
    assert len(rows) == 1
    assert rows[0]["cloud_resource_id"].endswith("/virtualmachines/api-node-01")
    assert rows[0]["start_line"] == 2
    assert "indexed_block" in rows[0]
