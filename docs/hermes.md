# Using the bridge with Hermes Agent

Two ways, both reversible. Neither touches your default provider.

## 1. Alias (fast, `-m mlai` / `/model mlai`)

```bash
hermes --profile NAME config set model.aliases.mlai.model mlai-code
hermes --profile NAME config set model.aliases.mlai.provider custom
hermes --profile NAME config set model.aliases.mlai.base_url http://127.0.0.1:8210/v1
hermes --profile NAME config set model.aliases.mlai.key_env MLAI_SHIM_KEY
echo "MLAI_SHIM_KEY=$(cat ~/.mlai-shim/key)" >> ~/.hermes/profiles/NAME/.env
```

Verify: `hermes --profile NAME chat -q "Reply with exactly: PONG" -m mlai`
and a tool probe: `... -q "Run 'echo TOOL_OK' with your terminal tool and print the output." -m mlai`

## 2. Provider row (appears in the desktop model picker)

```bash
hermes --profile NAME config set providers.mlai.base_url http://127.0.0.1:8210/v1
hermes --profile NAME config set providers.mlai.key_env MLAI_SHIM_KEY
hermes --profile NAME config set providers.mlai.api_mode chat_completions
hermes --profile NAME config set providers.mlai.models.mlai-code.context_length 1048576
```

The picker caches its catalogue: click **Refresh models** (or restart the app) before
expecting the row. Confirm what the picker will see:

```bash
HERMES_HOME=~/.hermes/profiles/NAME hermes doctor        # or open the picker
```

## Notes

* `MLAI_SHIM_KEY` belongs in `.env`, never in `config.yaml`.
* Keep an alias rather than replacing `model.default`: a plan-backed endpoint that
  disappears (external drive unmounted, sign-in revoked) should not break the default route.
* Remove everything:
  ```bash
  hermes --profile NAME config unset model.aliases.mlai
  hermes --profile NAME config unset providers.mlai
  # then delete the MLAI_SHIM_KEY line from the profile .env
  ```
