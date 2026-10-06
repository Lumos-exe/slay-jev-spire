"""Present native facts beside sequence choices, without estimating outcomes."""
from copy import deepcopy


def inline_actions(summary, plan, encoded_steps):
    cards={c['uuid']:c for c in summary.get('hand',[])}
    result=[]
    for step,encoded in zip(plan['sequence'],encoded_steps):
        item={'action':step['kind']}
        if step['kind']=='play':
            card=cards[step['card_uuid']]
            item.update(card=card.get('name',card['id']),card_id=card['id'],
                card_ref=encoded.get('card_uuid'),card_type=card.get('type'),
                cost_now=card.get('native_values',{}).get('cost_for_turn',card.get('cost')),
                free_to_play_once=card.get('free_to_play_once',False),
                free_to_play_now=card.get('native_values',{}).get('free_to_play'),
                native_text=card.get('description',card.get('raw_description')))
        elif step['kind']=='potion':
            potion=summary['potions'][step['potion_index']]
            item.update(action='potion_'+step['subaction'],slot=step['potion_index'],
                potion=potion.get('name',potion['id']),potency_now=potion.get('potency'),
                native_text_when_used=potion.get('description',potion.get('native_description')))
        if step.get('target_index') is not None:
            index=step['target_index'];enemy=summary['enemies'][index]
            item['target']={'index':index,'name':enemy.get('name',enemy.get('id'))}
        result.append(item)
    return result


def keyword_glossary(summary, registry):
    """Resolve actual registered terms, including definitions' cross-references."""
    definitions=dict(registry.get('keywords',{}))
    parents=registry.get('keyword_parents',{})
    card_keywords=registry.get('card_keywords') or {ident:entry.get('keywords',[]) for ident,entry in registry.get('cards',{}).items()}
    text=[];terms=set()
    def visit(value):
        if isinstance(value,list):
            for item in value:visit(item)
        elif isinstance(value,dict):
            definitions.update({k:v for k,v in value.get('keyword_descriptions',{}).items()
                                if isinstance(k,str) and isinstance(v,str)})
            for key in ('description','raw_description','native_description'):
                if isinstance(value.get(key),str):text.append(value[key])
            terms.update(k for k in value.get('keywords',[]) if isinstance(k,str))
            if 'uuid' in value:
                terms.update(card_keywords.get(value.get('id'),[]))
            for item in value.values():
                if isinstance(item,(dict,list)):visit(item)
    visit(summary)
    joined='\n'.join(text).casefold()
    terms.update(k for k in definitions if isinstance(k,str) and k.casefold() in joined)
    pending=list(terms);seen=set();result={}
    while pending:
        alias=pending.pop()
        if alias in seen:continue
        seen.add(alias)
        description=definitions.get(alias)
        if not isinstance(description,str):continue
        parent=parents.get(alias,alias)
        item=result.setdefault(parent,{'aliases':[],'native_description':description})
        item['aliases'].append(alias)
        lowered=description.casefold()
        pending.extend(k for k in definitions if k not in seen and k.casefold() in lowered)
    for item in result.values():item['aliases'].sort()
    return deepcopy(dict(sorted(result.items())))


INLINE_SCOPE=('actions逐项列出游戏中的当前卡牌类型、费用和效果原文，不是整串行动的预测结果。'
              '后续增益、减益和费用变化需结合机制判断。potion_discard仅丢弃药水，不施放其效果。')
KEYWORD_SCOPE='native_keyword_glossary来自游戏原生术语表；卡牌、能力或遗物明示的例外以各自效果为准。这些说明不是程序评分或推荐。'
