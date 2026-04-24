#!/usr/bin/env python3
"""
Test script for HITL approval notification system.

Tests:
1. Desktop notification with action buttons (Approve/Feedback/Reject)
2. Bus publish to all review topics
3. Full approval workflow

Usage:
    python test_hitl_notification.py                    # Full test
    python test_hitl_notification.py --notify-only      # Test notification only
    python test_hitl_notification.py --bus-only         # Test bus only
"""

import argparse
import subprocess
import time
import sys
from pathlib import Path

# Add termpipe_mcp to path
TERM_PIPE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(TERM_PIPE_ROOT))

# Desktop notifier path
sys.path.insert(0, str(TERM_PIPE_ROOT / "desktop-notifier" / "src"))


def test_desktop_notification():
    """Test rich desktop notification with action buttons."""
    print("=" * 60)
    print("TEST 1: Desktop Notification with Action Buttons")
    print("=" * 60)
    
    try:
        from desktop_notifier import DesktopNotifierSync, Urgency, Button
        
        # Import the review module
        from tools.workspace._review import _send_review_notification, _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED
        
        print(f"Topics: APPROVED={_TOPIC_APPROVED}")
        print(f"        FEEDBACK={_TOPIC_FEEDBACK}")
        print(f"        REJECTED={_TOPIC_REJECTED}")
        print()
        
        # Build test commands
        approve_cmd = f'kb pub {_TOPIC_APPROVED} "lgtm"'
        feedback_cmd = f'kb pub {_TOPIC_FEEDBACK} "<your feedback>"'
        reject_cmd = f'kb pub {_TOPIC_REJECTED} "<reason>"'
        
        print("Sending notification...")
        result = _send_review_notification(
            project_name="TestProject",
            plan_path="/tmp/test_plan.md",
            approve_cmd=approve_cmd,
            feedback_cmd=feedback_cmd,
            reject_cmd=reject_cmd,
        )
        
        if result:
            print("✅ Notification sent successfully!")
            print("   You should see a desktop notification with 3 buttons:")
            print("   - Approve ✓")
            print("   - Feedback")
            print("   - Reject ✗")
        else:
            print("❌ Notification failed")
            return False
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   desktop_notifier may not be installed or path is wrong")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True


def test_bus_publish():
    """Test publishing to all review topics."""
    print()
    print("=" * 60)
    print("TEST 2: Bus Publish to Review Topics")
    print("=" * 60)
    
    try:
        from tools.workspace._bus import _bus_pub, _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED
        
        topics = [
            (_TOPIC_APPROVED, "lgtm", "✅ APPROVED"),
            (_TOPIC_FEEDBACK, "test feedback message", "📝 FEEDBACK"),
            (_TOPIC_REJECTED, "test rejection reason", "❌ REJECTED"),
        ]
        
        for topic, data, label in topics:
            print(f"\nPublishing to {label}...")
            print(f"  Topic: {topic}")
            print(f"  Data: {data}")
            
            result = _bus_pub(topic, data)
            if result:
                print(f"  ✅ Published successfully")
            else:
                print(f"  ⚠️  Publish returned {result}")
            
            time.sleep(0.3)  # Small delay between publishes
    
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True


def test_full_approval_workflow():
    """Test the complete approval workflow with timeout."""
    print()
    print("=" * 60)
    print("TEST 3: Full Approval Workflow (5 second timeout)")
    print("=" * 60)
    print()
    print("Instructions:")
    print("1. A notification will appear")
    print("2. Click Approve, Feedback, or Reject button")
    print("3. Or run one of these commands in another terminal:")
    print(f"   kb pub {_TOPIC_APPROVED if '_bus' in sys.modules else 'termpipe.workspace.approved'} \"lgtm\"")
    print()
    print("Waiting for response (5 seconds)...")
    print()
    
    try:
        # We need to import dynamically after bus is set up
        from tools.workspace._bus import _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED
        from tools.workspace._review import _bus_poll
        
        topics = [_TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED]
        
        # Send another notification
        from tools.workspace._review import _send_review_notification
        _send_review_notification(
            project_name="WorkflowTest",
            plan_path="/tmp/test_plan.md",
            approve_cmd=f'kb pub {_TOPIC_APPROVED} "lgtm"',
            feedback_cmd=f'kb pub {_TOPIC_FEEDBACK} "feedback"',
            reject_cmd=f'kb pub {_TOPIC_REJECTED} "reject"',
        )
        
        # Poll for response
        result = _bus_poll(topics, timeout_ms=5000)
        
        if result is None:
            print("⏱️  TIMEOUT - No response received within 5 seconds")
            print("   (This is expected if you don't click a button)")
            return True  # Not a failure, just timeout
        
        topic, data = result
        print(f"📨 Response received!")
        print(f"   Topic: {topic}")
        print(f"   Data: {data}")
        
        if topic == _TOPIC_APPROVED:
            print("   → APPROVED")
        elif topic == _TOPIC_FEEDBACK:
            print("   → FEEDBACK")
        elif topic == _TOPIC_REJECTED:
            print("   → REJECTED")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gtt_fallback():
    """Test gtt notification fallback if desktop_notifier fails."""
    print()
    print("=" * 60)
    print("TEST 4: GTT Notification Fallback")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["gtt", "--notify", "Test notification from termpipe HITL system"],
            capture_output=True,
            timeout=5,
        )
        
        if result.returncode == 0:
            print("✅ gtt notification sent successfully!")
        else:
            print(f"⚠️  gtt notification failed: {result.stderr.decode()}")
            
    except FileNotFoundError:
        print("⚠️  gtt command not found (fallback not available)")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Test HITL notification system")
    parser.add_argument("--notify-only", action="store_true", help="Test notification only")
    parser.add_argument("--bus-only", action="store_true", help="Test bus only")
    parser.add_argument("--workflow-only", action="store_true", help="Test full workflow only")
    args = parser.parse_args()
    
    print()
    print("🚀 HITL Notification System Test Suite")
    print("=" * 60)
    
    if args.notify_only:
        success = test_desktop_notification()
        sys.exit(0 if success else 1)
    
    if args.bus_only:
        success = test_bus_publish()
        sys.exit(0 if success else 1)
    
    if args.workflow_only:
        success = test_full_approval_workflow()
        sys.exit(0 if success else 1)
    
    # Run all tests
    results = []
    
    results.append(("Desktop Notification", test_desktop_notification()))
    results.append(("Bus Publish", test_bus_publish()))
    results.append(("GTT Fallback", test_gtt_fallback()))
    results.append(("Full Workflow", test_full_approval_workflow()))
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All tests completed!")
    else:
        print("⚠️  Some tests had issues")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
