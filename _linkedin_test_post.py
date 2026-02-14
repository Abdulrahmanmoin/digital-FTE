import sys, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s - %(message)s')

from browser.linkedin_actions import execute_linkedin_post

print("=== TEST: CREATE NEW POST ===")
result = execute_linkedin_post(
    content="Testing automated posting system. If you see this, the AI employee pipeline is working!"
)
print(f"Post result: {result}")
