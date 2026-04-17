# patch_openbb_equity.py
# Fix OBBject_EquityInfo static import issue in openbb equity.py

equity_path = r'D:\conda_envs\openbb311\Lib\site-packages\openbb\package\equity.py'

with open(equity_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_import = '''from openbb_core.app.provider_interface import (
    OBBject_EquityInfo,
    OBBject_EquityScreener,
    OBBject_EquitySearch,
    OBBject_HistoricalMarketCap,
    OBBject_MarketSnapshots,
)'''

new_import = '''import openbb_core.app.provider_interface as _pi
# Dynamically resolve OBBject_* types (generated at runtime by openbb-core)
def _get_obbject_type(name, fallback=None):
    return getattr(_pi, name, fallback)
OBBject_EquityInfo = _get_obbject_type('OBBject_EquityInfo')
OBBject_EquityScreener = _get_obbject_type('OBBject_EquityScreener')
OBBject_EquitySearch = _get_obbject_type('OBBject_EquitySearch')
OBBject_HistoricalMarketCap = _get_obbject_type('OBBject_HistoricalMarketCap')
OBBject_MarketSnapshots = _get_obbject_type('OBBject_MarketSnapshots')'''

if old_import in content:
    content = content.replace(old_import, new_import)
    with open(equity_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched successfully.')
else:
    print('Pattern not found, checking content...')
    idx = content.find('OBBject_EquityInfo')
    print(f'OBBject_EquityInfo found at index: {idx}')
    print(content[max(0,idx-200):idx+100])
