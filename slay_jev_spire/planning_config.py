"""Configuration for the optional offline sequence simulator."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    beam_width: int = 32  # Legacy input; does not rank or prune.
    max_nodes: int = 8000
    max_depth: int = 24
    max_ms: int = 500

    def __post_init__(self):
        if any(type(x) is not int or x<1 for x in (self.beam_width,self.max_nodes,self.max_depth,self.max_ms)):
            raise ValueError('Search budgets must be positive integers.')
        if self.beam_width>128:raise ValueError('Beam width must not exceed 128.')
