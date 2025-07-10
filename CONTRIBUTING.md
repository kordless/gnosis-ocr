# 🤝 Contributing to Gnosis OCR

Thank you for considering contributing to Gnosis OCR! This guide will help you get started.

## 🚀 Quick Start

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/your-username/gnosis-ocr.git`
3. **Install** dependencies: `docker-compose up --build`
4. **Create** a branch: `git checkout -b feature/amazing-feature`
5. **Make** your changes
6. **Test** thoroughly
7. **Submit** a pull request

## 📋 Prerequisites

- **Docker Desktop** with GPU support
- **NVIDIA GPU** (for testing)
- **Git** version control
- **Basic knowledge** of Python, FastAPI, and Docker

## 🏗️ Development Setup

### Local Environment
```bash
# Clone your fork
git clone https://github.com/your-username/gnosis-ocr.git
cd gnosis-ocr

# Set up development environment
cp .env.cloudrun.example .env.cloudrun

# Start development server with hot reload
docker-compose up --build

# API will be available at http://localhost:7799
# Docs at http://localhost:7799/docs
```

### Testing
```bash
# Run tests
docker exec gnosis-ocr-local python -m pytest tests/

# Run specific test
docker exec gnosis-ocr-local python -m pytest tests/test_ocr.py

# Test with coverage
docker exec gnosis-ocr-local python -m pytest --cov=app tests/
```

## 📝 Code Style

We follow Python best practices and use automated formatting:

### Formatting
```bash
# Format code with black
black app/ tests/

# Sort imports
isort app/ tests/

# Lint with flake8
flake8 app/ tests/
```

### Code Standards
- **PEP 8** compliance
- **Type hints** for all functions
- **Docstrings** for classes and functions
- **Meaningful** variable names
- **Small, focused** functions

## 🧪 Testing Guidelines

### Test Structure
```python
def test_ocr_processing():
    """Test OCR processing with sample PDF."""
    # Arrange
    pdf_content = load_test_pdf()
    
    # Act
    result = ocr_service.process_pdf(pdf_content)
    
    # Assert
    assert result['status'] == 'completed'
    assert len(result['pages']) > 0
```

### Test Categories
- **Unit Tests** - Individual functions/classes
- **Integration Tests** - API endpoints
- **Performance Tests** - Speed and memory usage
- **GPU Tests** - CUDA functionality

## 📂 Project Structure

```
gnosis-ocr/
├── app/                    # Main application
│   ├── main.py            # FastAPI app
│   ├── ocr_service.py     # OCR processing
│   ├── storage_service.py # File storage
│   ├── models.py          # Data models
│   └── templates/         # Web UI
├── tests/                 # Test suite
├── scripts/               # Deployment scripts
├── docs/                  # Documentation
└── docker-compose.yml    # Development setup
```

## 🎯 Areas for Contribution

### 🐛 Bug Fixes
- GPU memory leaks
- File upload edge cases
- Error handling improvements
- Performance optimizations

### ✨ New Features
- Additional OCR models
- Batch processing
- API authentication
- Multi-language support
- Export formats (Word, Excel)

### 📚 Documentation
- API examples
- Tutorial videos
- Architecture diagrams
- Troubleshooting guides

### 🧪 Testing
- Edge case coverage
- Performance benchmarks
- Load testing
- Cross-platform testing

## 🔄 Pull Request Process

### 1. Before You Start
- Check existing [issues](https://github.com/your-org/gnosis-ocr/issues)
- Discuss major changes in an issue first
- Make sure tests pass locally

### 2. Making Changes
```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make your changes
# Add tests for new functionality
# Update documentation if needed

# Commit with clear messages
git commit -m "feat: add batch processing support"
```

### 3. Pull Request
- **Clear title** describing the change
- **Detailed description** of what and why
- **Screenshots** for UI changes
- **Test results** or performance data
- **Link** to related issues

### 4. Review Process
- Code review by maintainers
- Automated tests must pass
- Address feedback promptly
- Merge when approved

## 📋 Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new OCR model support
fix: resolve GPU memory leak
docs: update deployment guide
test: add integration tests
refactor: optimize storage service
style: format with black
chore: update dependencies
```

## 🚨 Issue Reporting

### Bug Reports
Please include:
- **Steps to reproduce**
- **Expected vs actual behavior**
- **System information** (OS, GPU, Docker version)
- **Log files** or error messages
- **Sample files** if relevant

### Feature Requests
Please include:
- **Use case** description
- **Current workarounds**
- **Proposed solution**
- **Implementation ideas**

## 🏆 Recognition

Contributors are recognized in:
- **README.md** contributor section
- **Release notes** for significant contributions
- **GitHub contributor graph**
- **Special thanks** in documentation

## 📞 Getting Help

- **GitHub Issues** - Bug reports and questions
- **GitHub Discussions** - General discussion
- **Discord** - Real-time chat (link in README)
- **Email** - security@gnosis-ocr.com for security issues

## 📄 License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT License).

## 🙏 Thank You

Every contribution makes Gnosis OCR better! Whether it's:
- Reporting bugs
- Suggesting features
- Writing documentation
- Submitting code
- Helping other users

**Your time and effort are appreciated!**

---

**Happy Contributing! 🚀**
