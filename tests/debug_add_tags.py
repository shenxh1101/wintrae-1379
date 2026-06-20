import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papertool.manager import add_tags, remove_tags
print("add_tags type:", type(add_tags))
print("add_tags:", add_tags)
print()

from papertool import manager
print("manager.add_tags:", manager.add_tags)
print("dir(manager):", [x for x in dir(manager) if 'add' in x or 'tag' in x.lower()])
