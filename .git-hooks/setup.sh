#!/bin/bash
# Setup script to configure git hooks
# Run this once after cloning the repository

echo "Setting up git hooks for cross-platform path transformation..."

# Configure git to use the hooks directory
git config core.hooksPath .git-hooks

echo "✓ Git hooks configured successfully!"
echo ""
echo "The following hooks are now active:"
echo "  - post-merge: runs after git pull"
echo "  - post-checkout: runs after git checkout"
echo ""
echo "These will automatically transform @HOME@ placeholders to your actual home directory path."
echo ""

# Run the transformation immediately for the current config
CONFIG_FILE="$(git rev-parse --show-toplevel)/config.toml"
HOME_DIR="$HOME"

if [ -f "$CONFIG_FILE" ] && grep -q '@HOME@' "$CONFIG_FILE" 2>/dev/null; then
    echo "Transforming current config.toml..."
    sed -i.bak "s|@HOME@|$HOME_DIR|g" "$CONFIG_FILE"
    rm -f "$CONFIG_FILE.bak"
    echo "✓ config.toml updated for this machine"
fi
