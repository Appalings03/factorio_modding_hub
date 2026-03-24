# core/validator.py

"""
Ce module est un STUB intentionnel dans le MVP.
L'architecture DB le supporte déjà :
- raw_json contient la donnée source complète
- prototype_properties contient les propriétés extraites et typées  
- prototype_relations contient les dépendances
- prototype_types contient l'arbre d'héritage avec types attendus
"""

from dataclasses import dataclass
from typing import Any

@dataclass
class ValidationError:
    prototype_name: str
    property_path: str
    expected_type: str
    actual_value: Any
    severity: str   # 'error' | 'warning' | 'info'

class PrototypeValidator:
    """
    Phase 2 : valider un prototype de mod contre le schéma officiel.
    
    Utilisation prévue :
        validator = PrototypeValidator(db_repo, version="1.1.107")
        errors = validator.validate(my_mod_prototype_dict)
    """
    
    def __init__(self, repository, version_tag: str):
        self.repo = repository
        self.version = version_tag
    
    def validate(self, prototype_data: dict) -> list[ValidationError]:
        # TODO Phase 2 :
        # 1. Récupérer le type officiel depuis prototype_types
        # 2. Pour chaque propriété : vérifier type, valeur, contraintes
        # 3. Remonter l'arbre d'héritage pour les propriétés héritées
        # 4. Retourner la liste des erreurs
        raise NotImplementedError("Phase 2")