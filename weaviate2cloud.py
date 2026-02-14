import uuid
import logging
from tqdm import tqdm
import weaviate
from weaviate.classes.config import Property, DataType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
LOCAL_WEAVIATE_URL = "http://localhost:8081"
CLOUD_WEAVIATE_URL = "mssp8ukoszwontickvnpeq.c0.asia-southeast1.gcp.weaviate.cloud"  # Without https://
CLOUD_API_KEY = "Qnd1UzZPbTVlRmxHUHJiaV9lSlJwM04vUW9MSk9FcnZBUDJFODRqbVNIdWxUY0d2Z3U3d3cra1VRUGRjPV92MjAw"  # Replace with fresh API key


def connect_local():
    try:
        client = weaviate.connect_to_local(
            host="localhost",
            port=8081,
            grpc_port=50051
        )
        if client.is_ready():
            logger.info("✅ Connected to local Weaviate")
            return client
        else:
            raise RuntimeError("Local Weaviate is not ready")
    except Exception as e:
        logger.error(f"❌ Failed to connect to local Weaviate: {e}")
        raise


def connect_cloud():
    try:
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=CLOUD_WEAVIATE_URL,
            auth_credentials=weaviate.auth.AuthApiKey(CLOUD_API_KEY)
        )
        if client.is_ready():
            logger.info("✅ Connected to cloud Weaviate")
            return client
        else:
            raise RuntimeError("Cloud Weaviate is not ready")
    except Exception as e:
        logger.error(f"❌ Failed to connect to cloud Weaviate: {e}")
        raise


def convert_datatype(datatype_str):
    """Convert string datatype to Weaviate DataType enum"""
    datatype_mapping = {
        'text': DataType.TEXT,
        'string': DataType.TEXT,
        'int': DataType.INT,
        'integer': DataType.INT,
        'number': DataType.NUMBER,
        'float': DataType.NUMBER,
        'boolean': DataType.BOOL,
        'date': DataType.DATE,
        'uuid': DataType.UUID,
        'object': DataType.OBJECT,
        'text[]': DataType.TEXT_ARRAY,
        'string[]': DataType.TEXT_ARRAY,
        'int[]': DataType.INT_ARRAY,
        'number[]': DataType.NUMBER_ARRAY,
        'boolean[]': DataType.BOOL_ARRAY,
        'date[]': DataType.DATE_ARRAY,
        'uuid[]': DataType.UUID_ARRAY,
        'object[]': DataType.OBJECT_ARRAY
    }
    
    if isinstance(datatype_str, list) and len(datatype_str) > 0:
        datatype_str = datatype_str[0].lower()
    elif isinstance(datatype_str, str):
        datatype_str = datatype_str.lower()
    else:
        return DataType.TEXT
    
    return datatype_mapping.get(datatype_str, DataType.TEXT)


def convert_properties(local_properties):
    """Convert local properties to cloud-compatible Property objects"""
    converted_properties = []
    property_names = []
    
    for prop in local_properties:
        try:
            if hasattr(prop, 'name'):
                name = prop.name
                datatype = convert_datatype(prop.data_type if hasattr(prop, 'data_type') else 'text')
                description = prop.description if hasattr(prop, 'description') else f"Property {name}"
            elif isinstance(prop, dict):
                name = prop.get('name', 'unknown')
                datatype = convert_datatype(prop.get('dataType', 'text'))
                description = prop.get('description', f"Property {name}")
            else:
                logger.warning(f"Unknown property format: {prop}")
                continue
            
            converted_prop = Property(
                name=name,
                data_type=datatype,
                description=description
            )
            converted_properties.append(converted_prop)
            property_names.append(name)
            
        except Exception as e:
            logger.warning(f"Error converting property {prop}: {e}")
            continue
    
    return converted_properties, property_names


def migrate_collection(local_client, cloud_client, collection_name):
    """Migrate a single collection from local to cloud"""
    try:
        local_collection = local_client.collections.get(collection_name)
        config = local_collection.config.get()
        logger.info(f"📋 Retrieved config for '{collection_name}'")
        
        # Convert properties and get property names
        converted_properties, property_names = convert_properties(config.properties)
        logger.info(f"📝 Found properties: {property_names}")
        
        if not converted_properties:
            logger.error(f"❌ No valid properties found for collection '{collection_name}'")
            return False
        
        if not cloud_client.collections.exists(collection_name):
            logger.info(f"🏗️ Creating collection '{collection_name}' in cloud...")
            
            cloud_client.collections.create(
                name=collection_name,
                properties=converted_properties,
                description=f"Migrated from local: {collection_name}",
                vectorizer_config=None
            )
            logger.info(f"✅ Created collection '{collection_name}' in cloud")
        else:
            logger.info(f"ℹ️ Collection '{collection_name}' already exists in cloud")
        
        cloud_collection = cloud_client.collections.get(collection_name)
        
        logger.info(f"🚀 Starting data migration for '{collection_name}'...")
        
        try:
            total_count = local_collection.aggregate.over_all(total_count=True).total_count
            logger.info(f"📊 Total objects to migrate: {total_count}")
        except Exception as e:
            logger.warning(f"⚠️ Could not get total count: {e}")
            total_count = None
        
        migrated_count = 0
        batch_objects = []
        batch_size = 50
        
        try:
            # Use specific property names instead of "*"
            iterator = local_collection.iterator(
                include_vector=True, 
                return_properties=property_names  # Use specific property names
            )
            
            for obj in tqdm(iterator, desc=f"Migrating {collection_name}", total=total_count):
                if obj is None:
                    continue
                
                object_data = weaviate.classes.data.DataObject(
                    properties=obj.properties if hasattr(obj, 'properties') else {},
                    vector=obj.vector if hasattr(obj, 'vector') and obj.vector else None,
                    uuid=obj.uuid if hasattr(obj, 'uuid') else None
                )
                batch_objects.append(object_data)
                
                if len(batch_objects) >= batch_size:
                    response = cloud_collection.data.insert_many(batch_objects)
                    
                    if response.has_errors:
                        logger.warning(f"⚠️ Batch had {len([e for e in response.errors if e])} errors")
                        # Log first few errors for debugging
                        for i, error in enumerate(response.errors[:3]):
                            if error:
                                logger.warning(f"  Error {i}: {error}")
                    
                    migrated_count += len([obj for obj in batch_objects if obj])
                    batch_objects = []
                    
                    if migrated_count % 500 == 0:
                        logger.info(f"📦 Migrated {migrated_count} objects so far...")
            
            # Insert remaining objects
            if batch_objects:
                response = cloud_collection.data.insert_many(batch_objects)
                
                if response.has_errors:
                    logger.warning(f"⚠️ Final batch had {len([e for e in response.errors if e])} errors")
                
                migrated_count += len([obj for obj in batch_objects if obj])
            
            logger.info(f"✅ Successfully migrated {migrated_count} objects for collection '{collection_name}'")
            
            # Verify migration
            try:
                cloud_count = cloud_collection.aggregate.over_all(total_count=True).total_count
                logger.info(f"🔍 Verification: Collection '{collection_name}' now has {cloud_count} objects in cloud")
            except Exception as e:
                logger.warning(f"⚠️ Could not verify count: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error during data migration for '{collection_name}': {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to migrate collection '{collection_name}': {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False


def main():
    local_client = None
    cloud_client = None
    
    try:
        logger.info("🔌 Connecting to local Weaviate...")
        local_client = connect_local()
        
        logger.info("🔌 Connecting to cloud Weaviate...")
        cloud_client = connect_cloud()
        
        local_collections = local_client.collections.list_all()
        collection_names = list(local_collections.keys())
        
        if not collection_names:
            logger.warning("⚠️ No collections found in local Weaviate")
            return
        
        logger.info(f"📋 Found collections in local Weaviate: {collection_names}")
        
        successful_migrations = 0
        for collection_name in collection_names:
            logger.info(f"\n🔄 Processing collection: {collection_name}")
            
            if migrate_collection(local_client, cloud_client, collection_name):
                successful_migrations += 1
            else:
                logger.error(f"❌ Failed to migrate collection: {collection_name}")
        
        logger.info(f"🎉 Migration completed! Successfully migrated {successful_migrations}/{len(collection_names)} collections")
        
        if successful_migrations > 0:
            logger.info("\n📊 Final verification:")
            try:
                cloud_collections = cloud_client.collections.list_all()
                logger.info(f"Collections now in cloud: {list(cloud_collections.keys())}")
                
                # Show counts for each collection
                for name in cloud_collections.keys():
                    try:
                        collection = cloud_client.collections.get(name)
                        count = collection.aggregate.over_all(total_count=True).total_count
                        logger.info(f"  {name}: {count} objects")
                    except Exception as e:
                        logger.warning(f"  {name}: Could not get count - {e}")
                        
            except Exception as e:
                logger.error(f"Error during final verification: {e}")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
    finally:
        if local_client:
            try:
                local_client.close()
                logger.info("🔌 Closed local Weaviate connection")
            except:
                pass
                
        if cloud_client:
            try:
                cloud_client.close()
                logger.info("🔌 Closed cloud Weaviate connection")
            except:
                pass


if __name__ == "__main__":
    main()
