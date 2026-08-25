# Workshop Deploy

## Azure Credentials

In Azure CLI run the following

```bash

SubID=$(az account list --query "[].{id:id}" -o tsv)

az ad sp create-for-rbac \
  --name workshop-deploy \
  --role Contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)

echo $SubID

```

in ~/.azure/credentials save below and change values from the Azure CLI

default can be changed to azure account name

```bash

[default]
subscription_id=xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
client_id=xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
secret=xxxxxxxxxxxxxxxxx
tenant=xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

```

## Build Container Image

```bash

docker build . -t github_workshop:latest

```

## Workshop Config

Each workshop folder can provide a `workshop_config.json` file.

Example (`github_copilot/workshop_config.json`):

```json
{
  "users_csv": "../users.csv",
  "credentials_path": "/Users/jesper/.azure/credentials",
  "azure_environment": "AzureCloud",
  "memory_reserve_percent": 10,
  "memory_reserve_min_mb": 512,
  "containers": [
    {
      "name": "instructor",
      "image": "ansiblenewclass:latest",
      "dockerfile": "Dockerfile",
      "build_context": ".",
      "memory_mb": 2000,
      "timeout_seconds": 1200
    },
    {
      "name": "student",
      "image": "ansiblenewclassstudent:latest",
      "memory_mb": 300,
      "timeout_seconds": 1200
    }
  ]
}
```

Notes:
- `azure_environment` is injected into containers as `AZURE_ENVIRONMENT` and `ARM_ENVIRONMENT`.
- If a container has `dockerfile`, the script builds the image before deployment.
- `build_context` is optional and defaults to `.`.
- `memory_mb` is a scheduling reservation, not a Docker hard memory limit.
- The scheduler keeps the larger of `memory_reserve_percent` or `memory_reserve_min_mb` free. The defaults are 10 percent and 512 MB.
- Container list order defines each user's required stage order. The first stage is prioritized across users.
- When a container finishes, Docker VM memory is measured again and newly available capacity is filled immediately.
- If the next first-stage job does not fit, a ready later-stage job may use the remaining memory.
- A failed or timed-out stage prevents later stages from running for that user. Containers are removed after completion.

## Run Deployment

```bash
python deploy_workshop.py github_copilot --log
```

`project_folder` is required and should point to a folder containing `workshop_config.json`.