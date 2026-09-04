"""SPEAKERPTZ v0.10 school field-validation toolkit.

Every module in this package is hardware-optional: the decision logic accepts
plain numbers and injected collaborators so it can be exercised without Dante
hardware, a PTZ camera, or school network access. Nothing here enables real
camera transmission; `real_control_enabled` remains the only gate.
"""
