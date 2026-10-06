"""Versioned, content-addressed native definitions. Missing entries never gate play."""
from hashlib import sha256
import json
from pathlib import Path


class NativeCatalogStore:
    def __init__(self, path):
        self.path=Path(path);self._stamp=None;self._data={};self.version=None

    def refresh(self):
        try:
            stat=self.path.stat();stamp=(stat.st_mtime_ns,stat.st_size)
            if stamp!=self._stamp:
                raw=self.path.read_bytes();data=json.loads(raw)
                if data.get('schema_version')!=1:raise ValueError('Unsupported catalog schema')
                if not all(isinstance(data.get(k),dict) for k in ('cards','relics')):
                    raise ValueError('Invalid catalog collections')
                self._data=data;self.version=sha256(raw).hexdigest();self._stamp=stamp
        except (OSError,ValueError,TypeError):
            self._data={};self.version=None;self._stamp=None
        return self

    def lookup(self, kind, identifier):
        return self._data.get(kind,{}).get(identifier)

    def keyword_context(self, summary):
        from .native_choice_text import keyword_glossary
        return keyword_glossary(summary,self._data)

    def localization(self):
        result={'cards':{},'relics':{}}
        for ident,entry in self._data.get('cards',{}).items():
            result['cards'][ident]={'DESCRIPTION':entry.get('raw_description'),
                'UPGRADE_DESCRIPTION':entry.get('upgrade',{}).get('raw_description'),
                'NATIVE_DEFINITION':entry,'CATALOG_VERSION':self.version}
        for ident,entry in self._data.get('relics',{}).items():
            result['relics'][ident]={'DESCRIPTION':entry.get('description'),
                'NATIVE_DEFINITION':entry,'CATALOG_VERSION':self.version}
        return result
