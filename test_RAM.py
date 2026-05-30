from transformers import AutoModel

# 1. Load the model
model = AutoModel.from_pretrained("microsoft/harrier-oss-v1-270m")

# 2. Ask the model for its exact memory footprint in bytes
memory_in_bytes = model.get_memory_footprint()

# 3. Convert bytes to Megabytes (MB) and print
memory_in_mb = memory_in_bytes / (1024 * 1024)
print(f"The model consumes exactly: {memory_in_mb:.2f} MB")