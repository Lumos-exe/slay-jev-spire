"""Budget-feasible purchase packages and native rebinding after each receipt."""
from copy import deepcopy
from hashlib import sha256
import json
from itertools import combinations

PURCHASES={'screen_shop_card','screen_shop_relic','screen_shop_potion','screen_shop_purge'}
PRICE_OR_STOCK_CHANGERS={'Membership Card','The Courier','Smiling Mask','Old Coin'}


def identity(action):
    item=action.get('item',{})
    return (action['kind'],item.get('id'),item.get('uuid'),item.get('upgrades'))


def generate_shop_plans(summary,actions,max_packages=512):
    """All singles remain native actions. Enumerate feasible larger subsets.

    Enumerating by cardinality keeps all pairs before triples if the explicit
    package budget is reached. No hidden top-N card-value heuristic is used.
    Price-changing relics are singleton observation boundaries.
    """
    if summary.get('screen_type')!='SHOP_SCREEN': return actions,{}
    gold=summary.get('gold',0)
    stock=[a for a in actions if a.get('kind') in PURCHASES]
    stable=[a for a in stock if a.get('item',{}).get('id') not in PRICE_OR_STOCK_CHANGERS]
    slots=sum(p.get('id')=='Potion Slot' for p in summary.get('potions',[]))
    plans=[];truncated=False
    for count in range(2,len(stable)+1):
        for items in combinations(stable,count):
            cost=sum(a['item']['price'] for a in items)
            if cost>gold or sum(a['kind']=='screen_shop_potion' for a in items)>slots: continue
            if len(plans)>=max_packages:
                truncated=True;break
            # Purge opens a selection screen; finish ordinary purchases first.
            steps=sorted(items,key=lambda a:a['kind']=='screen_shop_purge')
            payload=[(a['id'],identity(a),a['item']['price']) for a in steps]
            key=sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:12]
            plans.append(dict(id='shop_plan_'+key,kind='shop_plan',command='SHOP_PLAN',
                description='Buy a budgeted package; rebind each purchase to fresh native stock.',
                cost=cost,gold_left=gold-cost,steps=deepcopy(steps),
                purchases=[dict(action=a['id'],kind=a['kind'],item_id=a['item'].get('id','purge'),
                    card_uuid=a['item'].get('uuid'),price=a['item']['price']) for a in steps]))
        if truncated: break
    return actions+plans,dict(single_purchases=len(stock),packages=len(plans),package_limit=max_packages,
        complete_package_enumeration=not truncated,price_change_boundaries=sorted(PRICE_OR_STOCK_CHANGERS),
        scope='Feasible current-stock subsets, not card-value rankings. Potion replacement requires a separately observed discard.')


def bind_shop_queue(queue,summary,actions):
    """Prices/indices may change; never replay a stale CHOOSE index."""
    if not queue or summary.get('screen_type')!='SHOP_SCREEN': return None
    remaining=[a for a in actions if a.get('kind') in PURCHASES]
    rebound=[]
    for old in queue:
        actual=next((a for a in remaining if identity(a)==identity(old)),None)
        if actual is None: return None
        remaining.remove(actual);rebound.append(actual)
    if sum(a['item']['price'] for a in rebound)>summary.get('gold',0): return None
    slots=sum(p.get('id')=='Potion Slot' for p in summary.get('potions',[]))
    if sum(a['kind']=='screen_shop_potion' for a in rebound)>slots: return None
    return rebound[0]


def purchase_evidence(action):
    if action.get('kind')=='shop_plan':
        return dict(id=action['id'],cost=action['cost'],gold_left=action['gold_left'],purchases=action['purchases'])
    return dict(id=action['id'],kind=action['kind'],item=deepcopy(action.get('item')))
