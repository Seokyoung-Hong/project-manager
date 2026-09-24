# Sandol ProjectManager local extension data use

The extension runs on the device where it is installed. It sends the API token supplied during installation and the tool requests made in Claude Desktop to `https://project.sio2.kr` over HTTPS. The ProjectManager service processes those requests under the permissions of that token. Tool responses return to Claude Desktop and may be included in the Claude conversation.

The extension itself does not write the token or tool contents to local files and does not send requests to another service. The API token can be revoked at `https://project.sio2.kr/settings/tokens`. Uninstall the extension in Claude Desktop to remove its local tool connection.
