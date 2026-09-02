#!/bin/bash
# Digital Human Job Runner startup script - uses systemd for reliable service management.

systemctl --user start dhjr-backend.service dhjr-frontend.service ollama.service 2>/dev/null

echo '[dhjr] services started'
systemctl --user is-active dhjr-backend.service dhjr-frontend.service
