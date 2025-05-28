## Project Overview

VMware-Snapshot-Manager is a tool for managing VMware snapshots efficiently built with python, pyqt and pyvmomi. It allows users to manage and take VMware snapshots. 

## Copilot-Specific Guidance

- When generating code, always check for existing utility functions before introducing new ones.
- For VMware API interactions, prefer using official SDKs/libraries.
- Don't write tests for this application.
- For automation scripts, ensure cross-platform compatibility (Linux, Windows).
- Prioritize security: never expose credentials or sensitive information in code or logs.

## Useful References

- [VMware vSphere API Documentation](https://developer.vmware.com/apis/vsphere-automation/latest/)
- [Python vSphere SDK (pyvmomi)](https://github.com/vmware/pyvmomi)
