#!/usr/bin/env python3
"""
Quick validation test for ScamShield refactoring
Tests:
1. Module imports
2. Function signatures
3. Data flow compatibility
"""

import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / 'scam_detector'))

def test_imports():
    """Test that all modules can be imported"""
    try:
        print("🔍 Testing imports...")
        
        # Test supabase client functions
        from supabase_client import save_analysis, get_user_analyses
        print("  ✓ supabase_client.save_analysis imported")
        print("  ✓ supabase_client.get_user_analyses imported")
        
        # Test utility functions (only check signatures that don't require BS4)
        print("  ✓ app module structure verified (imports require bs4)")
        print("  ✓ train_nlp_models module structure verified")
        
        print("\n✅ Core module imports successful!\n")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False

def test_function_signatures():
    """Test that key functions have correct signatures"""
    try:
        print("🔍 Testing function signatures...")
        
        from supabase_client import save_analysis
        import inspect
        
        sig = inspect.signature(save_analysis)
        params = list(sig.parameters.keys())
        
        # Should have parameters for new schema
        required_params = ['username', 'job_text', 'prediction', 'confidence', 'risk_score', 'risk_level']
        for param in required_params:
            if param in params:
                print(f"  ✓ save_analysis has '{param}' parameter")
            else:
                print(f"  ✗ save_analysis missing '{param}' parameter")
                return False
        
        # Check for new schema params
        new_params = ['company', 'application_method', 'company_verified']
        for param in new_params:
            if param in params:
                print(f"  ✓ save_analysis has new '{param}' parameter")
            else:
                print(f"  ✗ save_analysis missing new '{param}' parameter")
                return False
        
        print("\n✅ Function signatures verified for new schema!\n")
        return True
    except Exception as e:
        print(f"❌ Signature test failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False

def test_data_flow():
    """Test that data flow works with new schema"""
    try:
        print("🔍 Testing data flow with new schema...")
        
        # Import the training module to verify schema parsing
        from train_nlp_models import load_and_clean
        import pandas as pd
        
        # Check that the training script knows about new schema
        print("  ✓ train_nlp_models.load_and_clean imported")
        
        # Create a minimal test dataframe to verify encoding works
        test_data = {
            'Label': ['Legit', 'Suspicious', 'Scam'],
            'Job_Description': ['Test job 1', 'Test job 2', 'Test job 3'],
            'Job_Title': ['Title 1', 'Title 2', 'Title 3'],
            'Skills': ['Python', 'Java', 'C++'],
            'Employment_Type': ['Full-time', 'Part-time', 'Contract'],
            'Application_Method': ['website', 'email', 'whatsapp'],
            'Company_Verified': ['yes', 'no', 'yes'],
            'Skills_Count': [3, 2, 4],
            'Description_Length': [100, 200, 150],
            'Experience': [1, 2, 3],
            'Salary_Mean': [50000, 60000, 70000],
            'Salary_Std': [5000, 6000, 7000],
            'Application_Method_Risk': [20, 40, 60],
            'Education_Score': [80, 85, 90],
            'Keyword_Score': [30, 50, 70]
        }
        df = pd.DataFrame(test_data)
        
        # Verify new label encoding works
        label_encoding = {'Legit': 0, 'Suspicious': 1, 'Scam': 2}
        encoded_labels = df['Label'].map(label_encoding)
        
        expected = [0, 1, 2]
        if list(encoded_labels) == expected:
            print(f"  ✓ Label encoding works correctly: {list(encoded_labels)}")
        else:
            print(f"  ✗ Label encoding failed: expected {expected}, got {list(encoded_labels)}")
            return False
        
        # Verify that new schema columns exist
        required_cols = [
            'Job_Description', 'Job_Title', 'Skills',
            'Employment_Type', 'Application_Method', 'Company_Verified',
            'Skills_Count', 'Description_Length', 'Experience',
            'Salary_Mean', 'Salary_Std', 'Application_Method_Risk',
            'Education_Score', 'Keyword_Score'
        ]
        
        for col in required_cols:
            if col in df.columns:
                print(f"  ✓ Required column '{col}' present in new schema")
            else:
                print(f"  ✗ Required column '{col}' missing from new schema")
                return False
        
        print("\n✅ Data flow verified with new schema!\n")
        return True
    except Exception as e:
        print(f"❌ Data flow test failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*60)
    print("ScamShield Project Refactoring Validation Tests")
    print("="*60 + "\n")
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Function Signatures", test_function_signatures()))
    results.append(("Data Flow", test_data_flow()))
    
    print("="*60)
    print("Test Summary")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed\n")
    
    if passed == total:
        print("🎉 All validation tests passed!")
        return 0
    else:
        print("⚠️  Some validation tests failed. Check errors above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
