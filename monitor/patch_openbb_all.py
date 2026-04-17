# patch_openbb_all.py - Fix all OBBject_* static import issues
import os
import re

pkg_dir = r'D:\conda_envs\openbb311\Lib\site-packages\openbb\package'

patched = 0
for fname in os.listdir(pkg_dir):
    if not fname.endswith('.py'):
        continue
    fpath = os.path.join(pkg_dir, fname)
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all OBBject_* names imported from provider_interface
    pattern = r'from openbb_core\.app\.provider_interface import \(([^)]+)\)'
    match = re.search(pattern, content)
    if not match:
        continue
    
    names_block = match.group(1)
    names = [n.strip().rstrip(',') for n in names_block.strip().split('\n') if n.strip().rstrip(',')]
    
    # Build replacement
    lines = ['import openbb_core.app.provider_interface as _pi_fix']
    for name in names:
        lines.append(f"{name} = getattr(_pi_fix, '{name}', None)")
    new_import = '\n'.join(lines)
    
    new_content = re.sub(pattern, new_import, content)
    if new_content != content:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'Patched: {fname} ({len(names)} types)')
        patched += 1

print(f'\nTotal patched: {patched} files')
