# Multi-Engine Support for Secret Scanning

**GitHub Issue**: [#91](https://github.com/RedHatProductSecurity/ai-guardian/issues/91)  
**Status**: ✅ **Phase 1 Complete (v1.5.0)** | ✅ **Phase 2 Complete (v1.6.0)**  
**Priority**: High (Production Ready)

## Summary

Multi-engine support for secret scanning is **fully implemented and production-ready** since v1.5.0. Users can choose or combine different secret detection tools based on their organization's requirements, compliance needs, and detection preferences.

## Background

AI Guardian supports multiple secret scanning engines since v1.5.0 (see `src/ai_guardian/scanners/engine_builder.py`). While Gitleaks is the default and an excellent open-source tool with 100+ built-in patterns, different organizations have varying needs:

### Why Multi-Engine Support?

**1. Different Strengths**
Each scanner has unique capabilities:
- **Gitleaks** - Fast, pattern-based, excellent for common secrets (AWS, GitHub, RSA keys)
- **TruffleHog** - High-accuracy with entropy analysis, finds custom/generic secrets without patterns
- **detect-secrets** - Baseline workflow for CI/CD, allows pre-commit hooks
- **Secretlint** - Pluggable architecture, custom rule development
- **GitGuardian** - Commercial service with 350+ secret types, active threat intelligence

**2. Compliance & Security Requirements**
- Healthcare (HIPAA): May require multiple scanning tools for defense-in-depth
- Finance (PCI-DSS): Auditors may mandate specific scanning engines
- Government (FedRAMP): Compliance frameworks may require tool diversity
- Enterprise policies: Some organizations have standardized on specific tools

**3. False Positive Management**
- Different engines have different false positive rates
- Running multiple engines with consensus mode reduces false positives
- Organizations can tune detection aggressiveness per use case

**4. Migration & Transition**
- Teams already using TruffleHog can migrate to ai-guardian gradually
- Test new engines alongside existing ones before switching
- No vendor lock-in - switch engines without changing infrastructure

### Currently Supported Engines

**Built-in Engine Presets** (see `src/ai_guardian/scanners/engine_builder.py`):
- **gitleaks** - Industry standard, fast, 100+ patterns
- **betterleaks** - Faster fork by original Gitleaks maintainers
- **leaktk** - Automatic pattern management, simpler setup
- **custom** - Define your own scanner engine

The implementation automatically tries engines in order and falls back to the first available engine.

## Current Implementation

### Configuration Format

The `engines` field is **fully functional** with support for both simple and advanced configurations:

#### Simple Format (Preset Names) - ✅ Implemented
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["gitleaks"]  // Single engine (default)
  }
}
```

```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["betterleaks", "gitleaks", "leaktk"]  // Try in order, use first available
  }
}
```

#### Advanced Format (Custom Engine Configuration) - ✅ Implemented
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": [
      {
        "type": "gitleaks",
        "binary": "/usr/local/bin/gitleaks",  // Custom path
        "extra_flags": ["--verbose"]
      },
      {
        "type": "custom",
        "binary": "my-scanner",
        "command_template": [
          "{binary}", "scan", "--json", "{report_file}", "{source_file}"
        ],
        "success_exit_code": 0,
        "secrets_found_exit_code": 1,
        "output_parser": "gitleaks"  // or "leaktk"
      }
    ]
  }
}
```

#### Real-World Examples (✅ Working Now)

**Example 1: Use BetterLeaks for Speed**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["betterleaks", "gitleaks"]  // Try betterleaks first, fallback to gitleaks
  }
}
```

**Example 2: Use LeakTK for Auto-Pattern Management**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["leaktk", "gitleaks"]  // LeakTK manages patterns automatically
  }
}
```

**Example 3: Custom Scanner Integration**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": [
      {
        "type": "custom",
        "binary": "my-company-scanner",
        "command_template": [
          "{binary}", "detect", "--format", "json", "--output", "{report_file}", "{source_file}"
        ],
        "success_exit_code": 0,
        "secrets_found_exit_code": 42,
        "output_parser": "gitleaks"
      },
      "gitleaks"  // Fallback to gitleaks if custom scanner not installed
    ]
  }
}
```

### Engine Architecture

#### Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class SecretMatch:
    """Single secret detection result."""
    rule_id: str
    description: str
    file: str
    line_number: int
    commit: Optional[str] = None
    secret: Optional[str] = None  # Redacted or None
    engine: str = None  # Which engine found it
    confidence: float = 1.0  # 0.0-1.0 confidence score

@dataclass
class ScanResult:
    """Result from a secret scanner."""
    has_secrets: bool
    secrets: List[SecretMatch]
    engine: str
    error: Optional[str] = None
    scan_time_ms: float = 0.0

class SecretScanner(ABC):
    """Abstract base class for secret scanning engines."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with configuration.
        
        Args:
            config: Engine-specific configuration from ai-guardian.json
        """
        self.config = config
        self.name = self.__class__.__name__.replace('Scanner', '').lower()
    
    @abstractmethod
    def scan(self, content: str, filename: str, context: Optional[Dict] = None) -> ScanResult:
        """
        Scan content for secrets.
        
        Args:
            content: Text content to scan
            filename: Filename for context
            context: Optional metadata (ide_type, hook_event, etc.)
            
        Returns:
            ScanResult with findings
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if scanner binary/library is installed and accessible.
        
        Returns:
            True if scanner is available, False otherwise
        """
        pass
    
    @abstractmethod
    def get_version(self) -> Optional[str]:
        """Get scanner version for logging."""
        pass
    
    def supports_pattern_server(self) -> bool:
        """Whether this engine supports pattern server integration."""
        return False

class GitleaksScanner(SecretScanner):
    """
    Gitleaks scanner implementation.
    
    Current implementation from check_secrets_with_gitleaks() will be
    refactored into this class.
    """
    
    def scan(self, content: str, filename: str, context: Optional[Dict] = None) -> ScanResult:
        # Refactor existing check_secrets_with_gitleaks logic here
        pass
    
    def is_available(self) -> bool:
        return shutil.which('gitleaks') is not None
    
    def get_version(self) -> Optional[str]:
        # Run 'gitleaks version'
        pass
    
    def supports_pattern_server(self) -> bool:
        return True  # Gitleaks supports custom TOML configs

class TruffleHogScanner(SecretScanner):
    """TruffleHog v3 scanner with entropy analysis."""
    
    def scan(self, content: str, filename: str, context: Optional[Dict] = None) -> ScanResult:
        # Run trufflehog with --no-verification or --only-verified
        pass
    
    def is_available(self) -> bool:
        return shutil.which('trufflehog') is not None

class DetectSecretsScanner(SecretScanner):
    """Yelp's detect-secrets scanner."""
    
    def scan(self, content: str, filename: str, context: Optional[Dict] = None) -> ScanResult:
        # Use detect-secrets scan --string
        pass
    
    def is_available(self) -> bool:
        try:
            import detect_secrets
            return True
        except ImportError:
            return False
```

#### Engine Registry & Factory

```python
class ScannerRegistry:
    """Registry of available secret scanning engines."""
    
    _scanners = {
        'gitleaks': GitleaksScanner,
        'trufflehog': TruffleHogScanner,
        'detect-secrets': DetectSecretsScanner,
        'secretlint': SecretlintScanner,
    }
    
    @classmethod
    def get_scanner(cls, engine_name: str, config: Dict) -> Optional[SecretScanner]:
        """Get scanner instance by name."""
        scanner_class = cls._scanners.get(engine_name)
        if scanner_class:
            return scanner_class(config)
        return None
    
    @classmethod
    def list_available(cls) -> List[str]:
        """List scanners that are actually installed."""
        available = []
        for name, scanner_class in cls._scanners.items():
            scanner = scanner_class({})
            if scanner.is_available():
                available.append(name)
        return available
```

#### Execution Strategies

```python
class ExecutionStrategy(ABC):
    """Strategy for executing multiple engines."""
    
    @abstractmethod
    def execute(self, scanners: List[SecretScanner], content: str, filename: str) -> ScanResult:
        """Execute scanners and combine results."""
        pass

class FirstMatchStrategy(ExecutionStrategy):
    """Use first enabled scanner, fall back if unavailable."""
    
    def execute(self, scanners: List[SecretScanner], content: str, filename: str) -> ScanResult:
        for scanner in scanners:
            if scanner.is_available():
                return scanner.scan(content, filename)
        return ScanResult(has_secrets=False, secrets=[], engine="none", 
                         error="No scanners available")

class AnyMatchStrategy(ExecutionStrategy):
    """Run all scanners, block if ANY finds secrets."""
    
    def execute(self, scanners: List[SecretScanner], content: str, filename: str) -> ScanResult:
        all_results = []
        all_secrets = []
        
        for scanner in scanners:
            if scanner.is_available():
                result = scanner.scan(content, filename)
                all_results.append(result)
                all_secrets.extend(result.secrets)
        
        # Deduplicate secrets by line number and rule
        unique_secrets = self._deduplicate(all_secrets)
        
        return ScanResult(
            has_secrets=len(unique_secrets) > 0,
            secrets=unique_secrets,
            engine="multiple",
        )

class ConsensusStrategy(ExecutionStrategy):
    """Block only if multiple scanners agree (reduce false positives)."""
    
    def __init__(self, threshold: int = 2):
        self.threshold = threshold
    
    def execute(self, scanners: List[SecretScanner], content: str, filename: str) -> ScanResult:
        # Group findings by line number, require threshold matches
        pass
```

### Engine Comparison

| Engine | Status | Type | Speed | Pattern Count | License | Installation |
|--------|--------|------|-------|---------------|---------|--------------|
| **Gitleaks** | ✅ Supported | Binary | ⚡ Fast | 100+ | MIT | `brew install gitleaks` |
| **BetterLeaks** | ✅ Supported | Binary | ⚡⚡ Faster | Same as Gitleaks | MIT | `brew install betterleaks` |
| **LeakTK** | ✅ Supported | Binary | ⚡⚡ Listen mode | Auto-managed | MIT | `brew install leaktk/tap/leaktk` |
| **Custom** | ✅ Supported | Any | Varies | User-defined | Any | User provides |
| **TruffleHog** | ✅ Supported (v1.6.0) | Binary | ⚡ Fast | 700+ | AGPL | `brew install trufflesecurity/trufflehog/trufflehog` |
| **detect-secrets** | ✅ Supported (v1.6.0) | Python | 🐢 Medium | 10+ plugins | Apache 2.0 | `pip install detect-secrets` |

**Currently Supported (v1.5.0+):**
- **Gitleaks** - Industry standard, fast, 100+ built-in patterns, works with pattern server
- **BetterLeaks** - Fork by original Gitleaks maintainers, faster performance, same output format
- **LeakTK** - Automatic pattern management, listen mode for near-zero overhead when daemon is running (~5ms vs ~200ms)
- **Custom** - Bring your own scanner, define command template and output parser

**Key Differences:**
- **Gitleaks**: Best for known patterns (AWS keys, GitHub tokens), pattern server support
- **BetterLeaks**: Same as Gitleaks but faster execution time
- **LeakTK**: Best when you don't want to manage pattern files manually. Uses `listen` mode as a persistent process when the daemon is running, eliminating subprocess spawn overhead

### License Considerations

**TruffleHog AGPL-3.0 Notice:**

TruffleHog is licensed under **AGPL-3.0** (GNU Affero General Public License), a copyleft license with strong requirements. However:

✅ **AI Guardian uses TruffleHog as an EXTERNAL TOOL** (subprocess execution only)  
✅ **This does NOT create a derivative work** (similar to Apache projects invoking Git)  
✅ **AI Guardian itself remains Apache-2.0** - no license contamination  

**What this means:**
- Installing TruffleHog via `ai-guardian scanner install trufflehog` shows a license notice
- Users acknowledge AGPL-3.0 terms before installation
- TruffleHog binary runs as a separate process (not linked/imported)
- No AGPL obligations apply to AI Guardian or your code

**Other Scanners:**
- **Gitleaks, BetterLeaks**: MIT (very permissive)
- **LeakTK, detect-secrets**: Apache-2.0 (same as ai-guardian)

For organizations with AGPL concerns, use gitleaks, betterleaks, leaktk, or detect-secrets instead.

## Implementation Plan

### Phase 1: Foundation & Refactoring (v1.8.0)

**Goal**: Extract current Gitleaks code into pluggable architecture without changing behavior

**Tasks**:
- [ ] **Create scanner abstraction** (`src/ai_guardian/scanners/base.py`)
  - [ ] Define `SecretScanner` ABC with `scan()`, `is_available()`, `get_version()` methods
  - [ ] Define `ScanResult` and `SecretMatch` dataclasses
  - [ ] Add docstrings and type hints

- [ ] **Refactor Gitleaks** (`src/ai_guardian/scanners/gitleaks.py`)
  - [ ] Extract `check_secrets_with_gitleaks()` logic into `GitleaksScanner` class
  - [ ] Move Gitleaks command building into `GitleaksScanner.scan()`
  - [ ] Preserve all current features: pattern server, ignore_files, ignore_tools, action modes
  - [ ] Keep backward compatibility - existing code should work unchanged

- [ ] **Add engine registry** (`src/ai_guardian/scanners/registry.py`)
  - [ ] Create `ScannerRegistry` class with engine registration
  - [ ] Implement `get_scanner(name, config)` factory method
  - [ ] Add `list_available()` to show installed engines
  - [ ] Register Gitleaks as default engine

- [ ] **Add execution strategies** (`src/ai_guardian/scanners/strategies.py`)
  - [ ] Create `ExecutionStrategy` ABC
  - [ ] Implement `FirstMatchStrategy` (default, backward compatible)
  - [ ] Add strategy selection based on config

- [ ] **Update configuration**
  - [ ] Make `secret_scanning.engines` field functional in schema
  - [ ] Add config parsing for engine list (simple and advanced formats)
  - [ ] Default to `["gitleaks"]` if not specified (backward compatible)
  - [ ] Add validation: warn if engine specified but not installed

- [ ] **Update main entry point** (`src/ai_guardian/__init__.py`)
  - [ ] Replace direct `check_secrets_with_gitleaks()` calls with engine registry
  - [ ] Load engine config from `secret_scanning.engines`
  - [ ] Instantiate scanner(s) via registry
  - [ ] Execute via strategy pattern

- [ ] **Testing**
  - [ ] Unit tests for `SecretScanner` interface
  - [ ] Integration tests with `GitleaksScanner`
  - [ ] Backward compatibility tests (no config change should break)
  - [ ] Test engine availability detection

- [ ] **Documentation**
  - [ ] Update README with engine configuration examples
  - [ ] Add migration guide from hardcoded Gitleaks
  - [ ] Document how to add new engines

**Acceptance Criteria**:
- ✅ All existing tests pass
- ✅ Default behavior unchanged (Gitleaks-only)
- ✅ No config changes needed for current users
- ✅ New `engines` field is functional
- ✅ Code is ready for additional engines

---

### Phase 2: Additional Engines (v1.6.0) ✅ COMPLETE

**Goal**: Add TruffleHog and detect-secrets support

**Status**: ✅ **Implemented and Released in v1.6.0**

**Tasks**:
- [x] **TruffleHog implementation** (`src/ai_guardian/scanners/output_parsers.py`)
  - [x] Create `TruffleHogOutputParser` class
  - [x] Implement newline-delimited JSON parsing
  - [x] Parse TruffleHog output format (SourceMetadata, DetectorName, Verified)
  - [x] Map TruffleHog detectors to standardized `SecretMatch` format
  - [x] Handle verified secrets flag
  - [x] Add tests with mock TruffleHog output (8 tests)

- [x] **detect-secrets implementation** (`src/ai_guardian/scanners/output_parsers.py`)
  - [x] Create `DetectSecretsOutputParser` class
  - [x] Parse baseline JSON format
  - [x] Support results dictionary structure
  - [x] Map plugin findings to `SecretMatch` format
  - [x] Add tests with mock detect-secrets output (9 tests)

- [x] **Execution strategies** (`src/ai_guardian/scanners/strategies.py`)
  - [x] Create `ExecutionStrategy` ABC
  - [x] Implement `FirstMatchStrategy` - use first available engine (backward compatible)
  - [x] Implement `AnyMatchStrategy` - run all engines, block if ANY finds secrets
  - [x] Implement `ConsensusStrategy` - block only if N engines agree (threshold configurable)
  - [x] Add result deduplication (same secret found by multiple engines → single result)
  - [x] Add verified secret preference in deduplication
  - [x] Add tests for all strategies and deduplication logic (21 tests)

- [x] **Configuration enhancements**
  - [x] Add `trufflehog` and `detect-secrets` to `ENGINE_PRESETS`
  - [x] Support both string and advanced engine config format
  - [x] Add `EXECUTION_STRATEGIES` registry
  - [x] Add `get_strategy()` factory function
  - ⏳ Schema updates for `execution_strategy` field (deferred to integration phase)

- [x] **Testing**
  - [x] Unit tests for TruffleHog parser (8 tests)
  - [x] Unit tests for detect-secrets parser (9 tests)
  - [x] Unit tests for execution strategies (21 tests)
  - [x] Strategy deduplication tests
  - [x] Consensus threshold tests
  - [x] All existing tests pass (1314 passed)

- [x] **Documentation**
  - [x] Update CHANGELOG.md with Phase 2 features
  - [x] Update MULTI_ENGINE_SUPPORT.md status to mark Phase 2 complete
  - [x] Add engine comparison in docs (TruffleHog vs detect-secrets vs Gitleaks)
  - [x] Configuration examples added to CHANGELOG
  - ⏳ README.md updates (deferred to integration phase)

**Acceptance Criteria**: ✅ ALL COMPLETE
- ✅ TruffleHog and detect-secrets parsers implemented
- ✅ Three execution strategies implemented (FirstMatch, AnyMatch, Consensus)
- ✅ Deduplication logic working correctly
- ✅ All 38 new tests pass
- ✅ All 1314 existing tests still pass (backward compatibility maintained)
- ✅ Documentation updated

---

### Phase 3: Advanced Features (v1.7.0) ✅

**Goal**: Production-ready multi-engine support with execution strategies

**Implemented** (v1.7.0):
- [x] **Execution strategy integration**
  - [x] `first-match` strategy (default, backward compatible)
  - [x] `any-match` strategy (block if ANY engine finds secrets)
  - [x] `consensus` strategy (block only if N engines agree)
  - [x] Strategy selection via `execution_strategy` config field
  - [x] `consensus_threshold` configurable

- [x] **Parallel engine execution**
  - [x] ThreadPoolExecutor for `any-match` and `consensus` strategies
  - [x] Max 4 concurrent workers
  - [x] Shared source file, per-engine report files

- [x] **Advanced deduplication**
  - [x] Fingerprint-based deduplication across engines (file + line + rule_id)
  - [x] Confidence scoring aggregation (highest confidence wins)
  - [x] Verified secret preference (TruffleHog verification)

- [x] **Per-engine configuration**
  - [x] `ignore_files` per engine (e.g., TruffleHog skips test fixtures)
  - [x] `pattern_server` per engine override
  - [x] `file_patterns` for file type routing

- [x] **File type routing**
  - [x] Route file types to specialized engines
  - [x] Fallback to all engines if no pattern matches

- [x] **Monitoring & metrics**
  - [x] Structured logging: engine, duration_ms, findings count
  - [x] Strategy-level logging: engines_run, combined_findings, deduplicated

- [x] **Console panel**
  - [x] "Engine Configuration" panel with JSON editor
  - [x] Strategy dropdown, consensus threshold input
  - [x] Live JSON validation

**Future** (not yet implemented):
- [ ] Additional engines (Secretlint, GitGuardian)
- [ ] Result caching per content hash
- [ ] Incremental scanning (only changed content)
- [ ] Enterprise features (remote config, audit logs, compliance reporting)

## Benefits

### 1. **Flexibility & Choice**
Organizations can use their preferred scanning tool based on:
- **Existing infrastructure**: Already using TruffleHog? Keep using it
- **Licensing requirements**: Choose open-source (MIT, Apache) vs AGPL vs commercial
- **Performance needs**: Fast binary scanners vs slower but more accurate
- **Detection philosophy**: Pattern-based vs entropy-based vs ML-based

### 2. **Defense in Depth**
Run multiple engines for comprehensive coverage:
- **Pattern-based + Entropy**: Gitleaks (patterns) + TruffleHog (entropy) catches both known and unknown secrets
- **Reduce blind spots**: Each engine has different strengths - combining them reduces false negatives
- **Cross-validation**: Multiple engines finding the same secret increases confidence

**Example**: Healthcare compliance requiring dual scanning
```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog"],
    "execution_strategy": "any-match"
  }
}
```

### 3. **False Positive Management**
Different strategies for different use cases:
- **Development**: `consensus` mode reduces interruptions (2+ engines must agree)
- **Production**: `any-match` mode for maximum security (any engine blocks)
- **Testing**: Run new engine in `log` mode alongside production engine

**Example**: Reduce dev team interruptions
```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog", "detect-secrets"],
    "execution_strategy": "consensus",
    "consensus_threshold": 2  // Block only if 2+ engines agree
  }
}
```

### 4. **Vendor Neutrality**
- **No lock-in**: Switch engines without infrastructure changes
- **Commercial flexibility**: Test commercial services (GitGuardian) alongside open-source
- **Sunset planning**: Gradually migrate off deprecated tools

### 5. **Gradual Migration**
Safely transition between tools:

**Week 1: Add new engine in log mode**
```json
{
  "secret_scanning": {
    "engines": [
      {"name": "gitleaks", "enabled": true, "priority": 1},
      {"name": "trufflehog", "enabled": true, "priority": 2, "action": "log-only"}
    ],
    "execution_strategy": "first-match"
  }
}
```

**Week 2: Run both engines**
```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog"],
    "execution_strategy": "any-match"  // Both engines block
  }
}
```

**Week 3: Remove old engine**
```json
{
  "secret_scanning": {
    "engines": ["trufflehog"]  // Migration complete
  }
}
```

### 6. **Future-Proof Architecture**
Easy to add new engines as they emerge:
- New ML-based scanners (GPT-powered secret detection)
- Cloud-specific scanners (AWS Macie, Azure Purview integration)
- Custom in-house scanners
- Community-contributed engine plugins

## Backward Compatibility

- **No `engines` config**: Default to Gitleaks (current behavior)
- **`engines: ["gitleaks"]`**: Explicit Gitleaks-only (same as current)
- **Pattern server**: Works with any engine that supports TOML configs
- **Existing configs**: Continue working unchanged

## Use Cases & Scenarios

### Scenario 1: Enterprise with Existing TruffleHog Investment
**Problem**: Company standardized on TruffleHog, but ai-guardian only supports Gitleaks
**Solution**: Add TruffleHog support so they can adopt ai-guardian without changing tools

```json
{
  "secret_scanning": {
    "engines": ["trufflehog"]
  }
}
```

### Scenario 2: Healthcare Compliance (HIPAA)
**Problem**: Auditors require "defense in depth" with multiple scanning tools
**Solution**: Run both Gitleaks and TruffleHog, block if either finds secrets

```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog"],
    "execution_strategy": "any-match",
    "pattern_server": {
      "url": "https://patterns.healthcare.company.com"  // HIPAA patterns
    }
  }
}
```

### Scenario 3: Development Team with High False Positives
**Problem**: Single engine causes too many false positives, developers bypass scanning
**Solution**: Require 2 out of 3 engines to agree before blocking

```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog", "detect-secrets"],
    "execution_strategy": "consensus",
    "consensus_threshold": 2
  }
}
```

### Scenario 4: Custom Secrets Not in Gitleaks
**Problem**: Company has proprietary API key format not detected by standard patterns
**Solution**: Use TruffleHog's entropy analysis to catch unknown secret formats

```json
{
  "secret_scanning": {
    "engines": [
      {
        "name": "gitleaks",
        "enabled": true,
        "config": {
          "use_pattern_server": true
        }
      },
      {
        "name": "trufflehog",
        "enabled": true,
        "config": {
          "entropy_threshold": 3.5,  // Custom format has high entropy
          "only_verified": false
        }
      }
    ],
    "execution_strategy": "any-match"
  }
}
```

### Scenario 5: Migration Without Downtime
**Problem**: Need to migrate from Gitleaks to commercial GitGuardian service
**Solution**: Test GitGuardian in log mode while Gitleaks continues blocking

```json
{
  "secret_scanning": {
    "engines": [
      {"name": "gitleaks", "enabled": true, "action": "block"},
      {"name": "gitguardian", "enabled": true, "action": "log-only"}
    ],
    "execution_strategy": "first-match"
  }
}
```
*Monitor logs for 2 weeks, then switch GitGuardian to block mode*

### Scenario 6: Different Engines for Different File Types
**Problem**: Want fast scanning for code, thorough scanning for config files
**Solution**: Use Gitleaks for `.js/.py` files, TruffleHog for `.env/.yaml`

```json
{
  "secret_scanning": {
    "engines": [
      {
        "name": "gitleaks",
        "enabled": true,
        "config": {
          "file_patterns": ["*.js", "*.py", "*.go"]
        }
      },
      {
        "name": "trufflehog",
        "enabled": true,
        "config": {
          "file_patterns": ["*.env*", "*.yaml", "*.json", "*.toml"]
        }
      }
    ]
  }
}
```

## Open Questions

### Technical Questions
1. **Parallel execution**: Should we run multiple engines in parallel for performance?
   - **Pro**: Faster total scan time
   - **Con**: More resource usage, harder to debug
   - **Proposal**: Make it configurable, default to sequential

2. **Conflicting results**: How to handle when engines disagree?
   - **Example**: Gitleaks says "AWS key", TruffleHog says "Generic high-entropy"
   - **Proposal**: Use execution strategy (any-match blocks on first, consensus requires agreement)

3. **Pattern server scope**: Should it be engine-specific or global?
   - **Proposal**: Global by default, with per-engine override capability
   ```json
   {
     "secret_scanning": {
       "pattern_server": {"url": "https://global.patterns.com"},
       "engines": [
         {
           "name": "gitleaks",
           "pattern_server": {"url": "https://gitleaks-specific.com"}
         }
       ]
     }
   }
   ```

4. **Ignore patterns per engine**: Do we need engine-specific ignore_files/ignore_tools?
   - **Use case**: TruffleHog has high false positives on test files, Gitleaks doesn't
   - **Proposal**: Support both global and per-engine ignore patterns

### Product Questions
1. **Default engine**: Should default remain Gitleaks, or auto-detect installed engines?
   - **Proposal**: Keep Gitleaks as default for backward compatibility

2. **Installation complexity**: How to guide users on installing multiple engines?
   - **Proposal**: Add `ai-guardian setup --verify-engines` command

3. **Performance impact**: What's acceptable overhead for running multiple engines?
   - **Proposal**: Benchmark target: <2x slowdown for dual-engine scanning

4. **Commercial engines**: Should we support commercial services (GitGuardian, etc.)?
   - **Proposal**: Yes, via API integration (separate from binary engines)

## Related Issues

- Relates to pattern server refactoring (#88)
- May impact secret scanning performance

## Decision Matrix

### Which Strategy Should I Use?

| Scenario | Recommended Strategy | Configuration |
|----------|---------------------|---------------|
| **Maximum security** (catch everything) | `any-match` | Run all engines, block if ANY finds secrets |
| **Reduce false positives** (dev productivity) | `consensus` (threshold: 2) | Block only if 2+ engines agree |
| **Single preferred engine** (simplest) | `first-match` | Try engines in order, use first that finds secrets |
| **Testing new engine** | `first-match` with log mode | Primary blocks, new engine logs only |
| **Compliance requirement** (dual scanning) | `any-match` | Run 2 specific engines |
| **Performance critical** | `first-match` | Use fastest engine (Gitleaks) |

### Which Engines Should I Use?

| Use Case | Recommended Engines | Why |
|----------|-------------------|-----|
| **Known secret types** (AWS, GitHub, etc.) | Gitleaks only | Fast, 100+ patterns, no API calls |
| **Custom/proprietary secrets** | Gitleaks + TruffleHog | Patterns + entropy catches both |
| **Unknown secret formats** | TruffleHog only | Entropy analysis finds high-randomness strings |
| **CI/CD baseline workflow** | detect-secrets | Prevent new secrets, allow existing (with baseline) |
| **Maximum coverage** | Gitleaks + TruffleHog + detect-secrets | Different strengths complement each other |
| **Verification required** | TruffleHog (verified mode) | API calls verify secrets are active |
| **No external dependencies** | Gitleaks | Pure pattern matching, no internet needed |

## Migration Guide for Users

### From: Hardcoded Gitleaks (current) → To: Explicit Engine Config

**Before (implicit):**
```json
{
  "secret_scanning": {
    "enabled": true
  }
}
```
*Gitleaks is hardcoded, no choice*

**After (explicit):**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["gitleaks"]  // Explicit, but same behavior
  }
}
```
*Same result, but now configurable*

### From: Gitleaks Only → To: Multiple Engines

**Step 1: Identify needs**
- Do you have custom secrets? → Add TruffleHog
- Do you need compliance? → Add second engine
- High false positives? → Use consensus strategy

**Step 2: Add second engine in log mode**
```json
{
  "secret_scanning": {
    "engines": [
      {"name": "gitleaks", "enabled": true, "action": "block"},
      {"name": "trufflehog", "enabled": true, "action": "log-only"}
    ],
    "execution_strategy": "first-match"
  }
}
```

**Step 3: Monitor logs for 1-2 weeks**
```bash
ai-guardian console  # Review what TruffleHog found
```

**Step 4: Enable blocking**
```json
{
  "secret_scanning": {
    "engines": ["gitleaks", "trufflehog"],
    "execution_strategy": "any-match"  // Both block now
  }
}
```

### From: External TruffleHog → To: ai-guardian with TruffleHog

**Before: Separate TruffleHog integration**
```bash
# Pre-commit hook or CI script
trufflehog filesystem . --json > secrets.json
```

**After: Integrated into ai-guardian**
```json
{
  "secret_scanning": {
    "enabled": true,
    "engines": ["trufflehog"],
    "pattern_server": null  // Don't need pattern server for TruffleHog
  }
}
```

Benefits:
- ✅ Unified configuration
- ✅ IDE integration (scan before AI sees content)
- ✅ Consistent ignore patterns
- ✅ Action modes (block vs log)

## References & Resources

### Engine Documentation
- **Gitleaks**: https://github.com/gitleaks/gitleaks
  - Docs: https://github.com/gitleaks/gitleaks#readme
  - Config: https://github.com/gitleaks/gitleaks#configuration
- **TruffleHog**: https://github.com/trufflesecurity/trufflehog
  - Docs: https://trufflesecurity.com/trufflehog
  - Detectors: https://github.com/trufflesecurity/trufflehog/tree/main/pkg/detectors
- **detect-secrets**: https://github.com/Yelp/detect-secrets
  - Docs: https://detect-secrets.readthedocs.io/
  - Plugins: https://detect-secrets.readthedocs.io/en/latest/plugins.html
- **Secretlint**: https://github.com/secretlint/secretlint
  - Docs: https://secretlint.github.io/
  - Rules: https://secretlint.github.io/docs/rules/

### Comparison & Research
- **Awesome Secret Detection**: https://github.com/edoardottt/awesome-secrets-detection
- **Secret Scanner Comparison** (2023): https://spectralops.io/blog/secret-scanning-tools-comparison/
- **OWASP Secret Management**: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

### Related Tools
- **GitGuardian**: https://www.gitguardian.com/ (Commercial, 350+ secret types)
- **GitHub Secret Scanning**: https://docs.github.com/en/code-security/secret-scanning
- **AWS Macie**: https://aws.amazon.com/macie/ (Cloud-specific)
- **Azure Key Vault Scanner**: https://azure.microsoft.com/en-us/products/key-vault

## Testing Strategy

### Unit Tests
- `tests/test_scanners/test_base.py` - Abstract base class contract
- `tests/test_scanners/test_gitleaks.py` - Gitleaks scanner implementation
- `tests/test_scanners/test_trufflehog.py` - TruffleHog scanner implementation
- `tests/test_scanners/test_detect_secrets.py` - detect-secrets implementation
- `tests/test_scanners/test_registry.py` - Engine registration and factory
- `tests/test_scanners/test_strategies.py` - Execution strategies

### Integration Tests
- `tests/test_multi_engine.py` - End-to-end multi-engine scenarios
- `tests/test_engine_fallback.py` - Fallback when engine unavailable
- `tests/test_deduplication.py` - Multiple engines finding same secret
- `tests/test_consensus.py` - Consensus strategy with various thresholds

### Performance Tests
- `tests/performance/test_scan_duration.py` - Measure scan time per engine
- `tests/performance/test_parallel_execution.py` - Parallel vs sequential
- Benchmark target: Multi-engine scanning ≤2x slower than single engine

### Compatibility Tests
- `tests/test_backward_compat.py` - No config change should break
- `tests/test_migration.py` - Migration from hardcoded Gitleaks
- Test matrix: Python 3.9-3.12, macOS/Linux/Windows

### Test Fixtures
```
tests/fixtures/secrets/
  ├── aws_key.txt              # Should be detected by all engines
  ├── high_entropy_custom.txt  # Only TruffleHog should detect
  ├── pattern_based.txt        # Only Gitleaks should detect
  └── false_positive.txt       # No engine should detect
```

## Acceptance Criteria

### Phase 1 (v1.8.0) - Foundation
- [ ] `SecretScanner` ABC defined with complete interface
- [ ] `GitleaksScanner` refactored from existing code
- [ ] `ScannerRegistry` can instantiate engines by name
- [ ] `FirstMatchStrategy` works with single engine
- [ ] **All 547+ existing tests pass** (backward compatibility)
- [ ] New config `engines: ["gitleaks"]` works identically to current behavior
- [ ] Config with no `engines` field defaults to Gitleaks
- [ ] Engine availability detection works (`is_available()`)
- [ ] Documentation explains new architecture

### Phase 2 (v1.9.0) - Additional Engines
- [ ] `TruffleHogScanner` implementation complete
  - [ ] Correctly parses TruffleHog JSON output
  - [ ] Handles verification API calls
  - [ ] Maps detectors to `SecretMatch` format
- [ ] `DetectSecretsScanner` implementation complete
  - [ ] Works with Python library
  - [ ] Supports baseline workflow
- [ ] `AnyMatchStrategy` runs all engines, blocks if any finds secrets
- [ ] `ConsensusStrategy` requires N engines to agree
- [ ] Result deduplication works correctly
  - [ ] Same secret found by multiple engines = 1 result
  - [ ] Different secrets = separate results
- [ ] **Performance**: Dual-engine scanning ≤2x slower than single
- [ ] **Performance**: Parallel execution faster than sequential (when enabled)
- [ ] Optional dependencies work: `uv pip install ai-guardian[trufflehog]` (or `pip install ai-guardian[trufflehog]`)
- [ ] Documentation includes:
  - [ ] Engine comparison table
  - [ ] Installation guide per engine
  - [ ] Configuration examples for common scenarios
  - [ ] When to use which strategy

### Phase 3 (v1.7.0) - Strategy Integration ✅
- [x] Per-engine pattern servers work
- [x] Per-engine ignore patterns work (ignore_files per engine)
- [x] Parallel execution stable and tested (ThreadPoolExecutor)
- [x] Monitoring metrics available:
  - [x] Scan duration per engine logged
  - [x] Engine availability tracked
  - [x] Structured strategy-level metrics
- [x] File type routing (file_patterns per engine)
- [x] Console panel for engine configuration
- [x] 30 new tests (92% scanner module coverage)

### Success Metrics
- **Adoption**: 20% of users configure multiple engines within 6 months
- **Performance**: 95% of scans complete in <500ms (single or multi-engine)
- **Reliability**: <1% engine failures in production
- **Support**: <5 issues/month related to multi-engine configuration

---

**Labels**: `enhancement`, `secret-scanning`, `architecture`  
**Milestone**: v2.0.0  
**Priority**: Medium (nice-to-have, not blocking)
