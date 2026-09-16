FROM python:3.14-slim

WORKDIR /app

# Update system packages to reduce vulnerabilities
RUN apt-get update && apt-get upgrade -y && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir -r /usr/local/lib/python3.14/site-packages/ansible_collections/azure/azcollection/requirements.txt

COPY 00_azure_class_setup.yml ./

ARG AZURE_PROFILE=AzureCloud
ENV AZURE_PROFILE=${AZURE_PROFILE}

CMD ["sh", "-c", "ansible-playbook -e adminUser=$username -e adminPassword=$password 00_azure_class_setup.yml"]