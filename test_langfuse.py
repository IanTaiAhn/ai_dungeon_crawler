import os
from langfuse.langchain import CallbackHandler

print("Environment vars:")
print(f"  PUBLIC_KEY: {os.environ.get('LANGFUSE_PUBLIC_KEY', 'NOT SET')[:20]}...")
print(f"  SECRET_KEY: {os.environ.get('LANGFUSE_SECRET_KEY', 'NOT SET')[:20]}...")
print(f"  HOST: {os.environ.get('LANGFUSE_HOST', 'NOT SET')}")

print("\nCreating CallbackHandler...")
handler = CallbackHandler()
print(f"  Handler created: {handler}")
print(f"  Client: {handler.langfuse}")
print(f"  Client host: {handler.langfuse.base_url if hasattr(handler.langfuse, 'base_url') else 'unknown'}")
