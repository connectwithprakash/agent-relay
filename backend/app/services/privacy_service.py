"""
Privacy service - Access control for relays
"""
from typing import Optional, Protocol


class RelayLike(Protocol):
    """Protocol for objects that have privacy attributes"""
    is_public: bool
    owner_id: Optional[str]


class PrivacyService:
    """Service for checking relay access permissions"""
    
    @staticmethod
    def check_access(relay: RelayLike, owner_id: Optional[str] = None) -> bool:
        """
        Check if access to relay is allowed.
        
        Args:
            relay: Object with is_public and owner_id attributes
            owner_id: The owner ID attempting access
            
        Returns:
            True if access is allowed, False otherwise
        """
        # Public relays are accessible to everyone
        if relay.is_public:
            return True
        
        # Private relays require owner_id match
        if relay.owner_id and owner_id == relay.owner_id:
            return True
        
        # Private relays require an authenticated owner or participant; absence
        # of owner metadata must never make a private relay public.
        return False
    
    @staticmethod
    def is_owner(relay: RelayLike, owner_id: Optional[str]) -> bool:
        """Check if the given owner_id is the relay owner"""
        if not relay.owner_id:
            return False
        return relay.owner_id == owner_id
