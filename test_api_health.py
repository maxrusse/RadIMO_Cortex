#!/usr/bin/env python3
"""
API Health Check Script for RadIMO Cortex Coordinator
Tests all three fallback strategies and API endpoints
"""

import sys
import yaml

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_check(passed, message):
    """Print a check with color coding"""
    symbol = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    print(f"{symbol} {message}")

def print_section(title):
    """Print a section header"""
    print(f"\n{BLUE}{'='*60}")
    print(f"{title}")
    print(f"{'='*60}{RESET}\n")

def check_imports():
    """Verify all required imports are available"""
    print_section("Checking Python Dependencies")

    required_modules = [
        ('flask', 'Flask'),
        ('pandas', 'pandas'),
        ('yaml', 'PyYAML'),
        ('pytz', 'pytz'),
    ]

    all_ok = True
    for module_name, package_name in required_modules:
        try:
            __import__(module_name)
            print_check(True, f"{package_name} installed")
        except ImportError:
            print_check(False, f"{package_name} NOT installed")
            all_ok = False

    return all_ok

def check_config():
    """Verify config.yaml structure"""
    print_section("Checking Configuration File")

    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        # Check balancer section
        if 'balancer' not in config:
            print_check(False, "balancer section missing")
            return False

        balancer = config['balancer']

        # Check fallback_strategy
        if 'fallback_strategy' not in balancer:
            print_check(False, "fallback_strategy not configured")
            return False

        strategy = balancer['fallback_strategy']
        valid_strategies = ['skill_priority', 'modality_priority', 'pool_priority']

        if strategy in valid_strategies:
            print_check(True, f"fallback_strategy = '{strategy}'")
        else:
            print_check(False, f"Invalid strategy '{strategy}' (valid: {valid_strategies})")
            return False

        # Check other balancer settings
        settings = {
            'enabled': bool,
            'min_assignments_per_skill': int,
            'imbalance_threshold_pct': (int, float),
            'allow_fallback_on_imbalance': bool,
            'fallback_chain': dict
        }

        for setting, expected_type in settings.items():
            if setting in balancer:
                value = balancer[setting]
                if isinstance(expected_type, tuple):
                    type_ok = isinstance(value, expected_type)
                else:
                    type_ok = isinstance(value, expected_type)
                print_check(type_ok, f"{setting} = {value}")
            else:
                print_check(False, f"{setting} missing")

        # Check modality_fallbacks
        if 'modality_fallbacks' in config:
            print_check(True, f"modality_fallbacks configured: {list(config['modality_fallbacks'].keys())}")
        else:
            print_check(True, "modality_fallbacks not configured (optional)")

        # Check modalities
        if 'modalities' in config:
            modalities = list(config['modalities'].keys())
            print_check(True, f"modalities: {modalities}")
        else:
            print_check(False, "modalities section missing")
            return False

        # Check skills
        if 'skills' in config:
            skills = list(config['skills'].keys())
            print_check(True, f"skills: {skills}")
        else:
            print_check(False, "skills section missing")
            return False

        return True

    except FileNotFoundError:
        print_check(False, "config.yaml not found")
        return False
    except yaml.YAMLError as e:
        print_check(False, f"YAML syntax error: {e}")
        return False

def check_app_structure():
    """Verify app.py structure"""
    print_section("Checking Application Structure")

    try:
        with open('app.py', 'r') as f:
            content = f.read()

        # Check for strategy functions
        functions = [
            'get_next_available_worker',
            '_get_worker_skill_priority',
            '_get_worker_modality_priority',
            '_get_worker_pool_priority',
        ]

        for func in functions:
            if f'def {func}(' in content:
                print_check(True, f"Function '{func}' exists")
            else:
                print_check(False, f"Function '{func}' NOT FOUND")
                return False

        # Check for API endpoints
        endpoints = [
            "@app.route('/api/<modality>/<role>', methods=['GET'])",
            "@app.route('/api/<modality>/<role>/strict', methods=['GET'])",
            "@app.route('/api/quick_reload', methods=['GET'])",
        ]

        for endpoint in endpoints:
            if endpoint in content:
                print_check(True, f"Endpoint {endpoint.split('[')[0]}")
            else:
                print_check(False, f"Endpoint {endpoint.split('[')[0]} NOT FOUND")
                return False

        # Check strategy dispatcher logic
        if "strategy = BALANCER_SETTINGS.get('fallback_strategy'" in content:
            print_check(True, "Strategy dispatcher implemented")
        else:
            print_check(False, "Strategy dispatcher NOT FOUND")
            return False

        if "if strategy == 'modality_priority':" in content:
            print_check(True, "modality_priority strategy routing")
        else:
            print_check(False, "modality_priority routing missing")
            return False

        if "elif strategy == 'pool_priority':" in content:
            print_check(True, "pool_priority strategy routing")
        else:
            print_check(False, "pool_priority routing missing")
            return False

        return True

    except FileNotFoundError:
        print_check(False, "app.py not found")
        return False

def check_fallback_chain_logic():
    """Verify fallback chain configuration structure"""
    print_section("Checking Fallback Chain Logic")

    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        if 'balancer' not in config or 'fallback_chain' not in config['balancer']:
            print_check(False, "fallback_chain not configured")
            return False

        fallback_chain = config['balancer']['fallback_chain']

        # Check each skill has a fallback configuration
        skills = config.get('skills', {})
        for skill in skills.keys():
            if skill in fallback_chain:
                chain = fallback_chain[skill]
                if isinstance(chain, list):
                    print_check(True, f"{skill}: {chain}")
                else:
                    print_check(False, f"{skill}: invalid type (should be list)")
            else:
                print_check(True, f"{skill}: not in fallback_chain (will use default)")

        # Check modality fallbacks if configured
        if 'modality_fallbacks' in config:
            mod_fallbacks = config['modality_fallbacks']
            modalities = config.get('modalities', {})

            for mod in modalities.keys():
                if mod in mod_fallbacks:
                    chain = mod_fallbacks[mod]
                    print_check(True, f"Modality {mod} → {chain}")
                else:
                    print_check(True, f"Modality {mod}: no fallback (stays local)")

        return True

    except Exception as e:
        print_check(False, f"Error checking fallback chains: {e}")
        return False

def check_readme_documentation():
    """Verify README has documentation"""
    print_section("Checking Documentation")

    try:
        with open('README.md', 'r') as f:
            readme = f.read()

        docs_to_check = [
            ('skill_priority', 'skill_priority strategy documented'),
            ('modality_priority', 'modality_priority strategy documented'),
            ('pool_priority', 'pool_priority strategy documented'),
            ('fallback_strategy', 'fallback_strategy configuration documented'),
            ('Configuration Reference', 'Configuration section exists'),
        ]

        for search_term, description in docs_to_check:
            if search_term in readme:
                print_check(True, description)
            else:
                print_check(False, f"{description} - NOT FOUND")

        return True

    except FileNotFoundError:
        print_check(False, "README.md not found")
        return False

def print_api_test_guide():
    """Print guide for manually testing the APIs"""
    print_section("API Testing Guide")

    print(f"{YELLOW}Manual API Testing:{RESET}\n")

    print("1. Start the Flask application:")
    print("   $ flask --app app run --debug\n")

    print("2. Test basic assignment (uses configured strategy):")
    print("   $ curl http://localhost:5000/api/ct/herz\n")

    print("3. Test strict mode (no fallbacks):")
    print("   $ curl http://localhost:5000/api/ct/herz/strict\n")

    print("4. Test quick reload (get stats):")
    print("   $ curl http://localhost:5000/api/quick_reload?modality=ct\n")

    print("5. Check logs for strategy execution:")
    print("   $ tail -f logs/selection.log\n")

    print(f"{YELLOW}Strategy Testing:{RESET}\n")

    strategies = ['skill_priority', 'modality_priority', 'pool_priority']
    for strategy in strategies:
        print(f"To test {strategy}:")
        print(f"  1. Set in config.yaml: fallback_strategy: {strategy}")
        print(f"  2. Restart Flask app")
        print(f"  3. Make API request and check logs/selection.log")
        print(f"  4. Look for: 'Building candidate pool' (pool_priority)")
        print(f"     or 'Trying skill X across modalities' (modality_priority)")
        print(f"     or standard modality-first logging (skill_priority)\n")

def main():
    """Run all health checks"""
    print(f"\n{BLUE}{'='*60}")
    print("RadIMO Cortex Coordinator - API Health Check")
    print(f"{'='*60}{RESET}\n")

    all_checks = [
        ("Python Dependencies", check_imports),
        ("Configuration", check_config),
        ("Application Structure", check_app_structure),
        ("Fallback Chain Logic", check_fallback_chain_logic),
        ("Documentation", check_readme_documentation),
    ]

    results = []
    for name, check_func in all_checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print_check(False, f"{name}: {e}")
            results.append((name, False))

    # Print summary
    print_section("Health Check Summary")

    all_passed = all(result for _, result in results)

    for name, passed in results:
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {name}: {status}")

    if all_passed:
        print(f"\n{GREEN}✓ All health checks passed!{RESET}")
        print(f"\n{GREEN}Ready for testing!{RESET}")
        print_api_test_guide()
        return 0
    else:
        print(f"\n{RED}✗ Some health checks failed{RESET}")
        print(f"\n{YELLOW}Fix the issues above before testing{RESET}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
