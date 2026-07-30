# Security Policy

## Supported Versions

| Version | Supported               |
| ------- | ----------------------- |
| 0.1.x   | ✅ (active development) |

## Reporting a Vulnerability

Please report security vulnerabilities to **security@projectionai.dev**.

We will acknowledge receipt within 48 hours and provide an initial assessment
within 5 business days. We ask that you do not publicly disclose the issue
until we have had a reasonable opportunity to address it.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Any suggested fix (if known)

## Disclosure Timeline

- **0-48h**: Acknowledgment of receipt
- **5 business days**: Initial assessment and severity classification
- **30 days**: Target for releasing a fix, depending on severity

## Security Considerations

- This application uses AI provider API keys — never commit `.env` to version control
- All user data files (.projectai, .proj) should be treated as opaque blobs
- The application can load external shaders — only use trusted sources
