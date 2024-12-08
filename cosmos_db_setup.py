import os
import logging
from azure.cosmos import CosmosClient, exceptions

# Set up logging
logging.basicConfig(level=logging.INFO)

# Fetch Cosmos DB credentials from environment variables
COSMOS_ENDPOINT = os.getenv('COSMOS_ENDPOINT')
COSMOS_KEY = os.getenv('COSMOS_KEY')
DATABASE_NAME = 'MediaDatabase'
CONTAINER_NAME = 'MediaContainer'

if not COSMOS_ENDPOINT or not COSMOS_KEY:
    raise EnvironmentError("Cosmos DB credentials are not set in environment variables.")

# Initialize Cosmos client
client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)

# Create database and container if not exists
database = client.create_database_if_not_exists(id=DATABASE_NAME)
logging.info(f"Database '{DATABASE_NAME}' created or already exists.")

container = database.create_container_if_not_exists(
    id=CONTAINER_NAME,
    partition_key={'paths': ['/id'], 'kind': 'Hash'},
    offer_throughput=400
)
logging.info(f"Container '{CONTAINER_NAME}' created or already exists.")
