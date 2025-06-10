# Development Workflow

## Branch Strategy

```
main (protected, stable releases only)
├── develop (integration branch for features)
├── feature/your-feature-name
└── hotfix/urgent-fix-name
```

## Development Process

### 1. Feature Development
```bash
# Start from develop branch
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/your-feature-name

# Make your changes and commit
git add .
git commit -m "Add your feature"

# Push and create PR to develop
git push origin feature/your-feature-name
```

### 2. Integration Testing
- Features merge into `develop` branch
- CI runs tests on every push to `develop`
- Manual testing performed on `develop`

### 3. Release Process
```bash
# When ready to release from develop
git checkout main
git merge develop
git tag -a v1.2.4 -m "Release v1.2.4"
git push origin main --tags
```

## CI/CD Behavior

### On Every Push/PR:
- ✅ Run tests (fast, ~2 minutes)
- ✅ Validate code
- ✅ Check version format

### On Release Tags Only:
- 🔨 Build Windows executable
- 🔨 Build macOS app bundle  
- 📦 Create GitHub release with assets

## Release Checklist

1. Update `version.py` with new version
2. Test locally on both platforms
3. Merge to main and tag
4. CI automatically builds and releases
5. Manually write release notes on GitHub

This approach saves CI resources and follows industry best practices.