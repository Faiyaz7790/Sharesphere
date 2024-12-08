import os
from flask import Flask, request, jsonify
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, exceptions
import uuid
import logging
import datetime

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO)

# Fetch credentials from environment variables
COSMOS_ENDPOINT = os.getenv('COSMOS_ENDPOINT')
COSMOS_KEY = os.getenv('COSMOS_KEY')
AZURE_BLOB_CONNECTION_STRING = os.getenv('AZURE_BLOB_CONNECTION_STRING')
BLOB_CONTAINER_NAME = os.getenv('BLOB_CONTAINER_NAME', 'mediafiles')  # Configurable
DATABASE_NAME = os.getenv('COSMOS_DATABASE_NAME', 'MediaDatabase')  # Configurable
CONTAINER_NAME = os.getenv('COSMOS_CONTAINER_NAME', 'MediaContainer')  # Configurable
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'mp4'}
MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 50))  # Configurable

# Validate credentials
if not all([COSMOS_ENDPOINT, COSMOS_KEY, AZURE_BLOB_CONNECTION_STRING]):
    logging.error("Missing required environment variables.")
    raise EnvironmentError("Please set COSMOS_ENDPOINT, COSMOS_KEY, and AZURE_BLOB_CONNECTION_STRING.")

# Initialize clients
cosmos_client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
blob_service_client = BlobServiceClient.from_connection_string(AZURE_BLOB_CONNECTION_STRING)

# Create container client
database = cosmos_client.create_database_if_not_exists(id=DATABASE_NAME)
container = database.create_container_if_not_exists(
    id=CONTAINER_NAME,
    partition_key={'paths': ['/id'], 'kind': 'Hash'},
    offer_throughput=400
)
blob_container_client = blob_service_client.get_container_client(BLOB_CONTAINER_NAME)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file):
    """Validate file content type and size."""
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        return False, "File exceeds maximum allowed size"
    return True, None

@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled exception: {str(e)}")
    return jsonify({"error": "Internal server error"}), 500

@app.route('/upload', methods=['POST'])
def upload_media():
    try:
        file = request.files['file']
        if not file or not allowed_file(file.filename):
            return jsonify({"error": "Unsupported file type"}), 400
        
        is_valid, error = validate_file(file)
        if not is_valid:
            return jsonify({"error": error}), 400

        unique_filename = str(uuid.uuid4()) + "-" + file.filename
        blob_client = blob_container_client.get_blob_client(unique_filename)

        # Stream upload to Blob Storage
        blob_client.upload_blob(file.stream, overwrite=True)

        media_entry = {
            'id': unique_filename,
            'filename': file.filename,
            'url': blob_client.url,
            'upload_date': datetime.datetime.utcnow().isoformat()
        }
        container.create_item(body=media_entry)

        logging.info(f"File uploaded successfully: {file.filename}")
        return jsonify({"message": "File uploaded successfully", "url": blob_client.url}), 201

    except exceptions.CosmosHttpResponseError as e:
        logging.error(f"Cosmos DB error: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        logging.error(f"Upload error: {str(e)}")
        return jsonify({"error": "Upload failed"}), 500

@app.route('/media', methods=['GET'])
def get_media():
    try:
        limit = int(request.args.get('limit', 10))
        items = list(container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True
        ))[:limit]
        return jsonify(items), 200
    except Exception as e:
        logging.error(f"Read error: {str(e)}")
        return jsonify({"error": "Failed to fetch media"}), 500

@app.route('/media/<media_id>', methods=['PUT'])
def update_media(media_id):
    try:
        new_data = request.json
        allowed_fields = {'filename'}
        invalid_fields = [key for key in new_data.keys() if key not in allowed_fields]
        if invalid_fields:
            return jsonify({"error": f"Invalid fields: {', '.join(invalid_fields)}"}), 400

        item = container.read_item(item=media_id, partition_key=media_id)
        item.update(new_data)
        container.replace_item(item=media_id, body=item)

        logging.info(f"Media updated: {media_id}")
        return jsonify({"message": "Media updated successfully"}), 200
    except exceptions.CosmosHttpResponseError as e:
        logging.error(f"Cosmos DB error: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        logging.error(f"Update error: {str(e)}")
        return jsonify({"error": "Failed to update media"}), 500

@app.route('/media/<media_id>', methods=['DELETE'])
def delete_media(media_id):
    try:
        container.delete_item(item=media_id, partition_key=media_id)
        blob_client = blob_container_client.get_blob_client(media_id)
        blob_client.delete_blob()

        logging.info(f"Media deleted: {media_id}")
        return jsonify({"message": "Media deleted successfully"}), 200
    except exceptions.CosmosHttpResponseError as e:
        logging.error(f"Cosmos DB error: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        logging.error(f"Delete error: {str(e)}")
        return jsonify({"error": "Failed to delete media"}), 500

if __name__ == '__main__':
    app.run(debug=True)
