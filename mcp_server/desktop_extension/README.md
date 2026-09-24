# Claude Desktop local extension

This MCPB extension runs a small MCP server on the installed device. It retrieves the live tool list and calls the public HTTP relay. The extension is installed per device; it is not an account-wide remote connector.

1. Create an API token at `https://project.sio2.kr/settings/tokens`. Choose `read` for viewing or `write` for editing.
2. Install `../sandol-project-manager-local.mcpb` in Claude Desktop: **Settings → Extensions → Advanced settings → Install Extension…**
3. Enter the API token in the extension's sensitive configuration field.
4. Start a new Claude Desktop chat and ask it to call `get_guide`, then use the ProjectManager tools.

The token is stored in Claude Desktop's local credential storage and sent only to `https://project.sio2.kr`. Revoke it in ProjectManager Settings to remove access. On another device, do not install this extension or enter its token. Remove the existing remote ProjectManager connector on this Claude account if you want these tools to appear only on the selected desktop.
