# Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io/), certificate
by [SignPath Foundation](https://signpath.org/).

This policy applies once the project's SignPath Foundation open-source
subscription has been approved and configured. Releases published before that
integration may be unsigned.

## Scope

The policy covers the official Windows executable and installer published on
the project's [GitHub Releases](https://github.com/e-Lopes/chess-book-diagram-extractor/releases)
page. It does not cover local, unofficial, or modified builds.

## Build and signing process

1. Official releases are built from a version tag in the public GitHub
   repository.
2. GitHub Actions runs the automated tests and creates the Windows artifacts.
3. SignPath verifies the build origin and signs the approved artifacts.
4. A project approver must manually approve each signing request.
5. Signed installers are published as GitHub Release assets without subsequent
   modification.

## Team roles

This is a solo-maintained open-source project. The required roles are held by
the project maintainer:

| Role | Member |
| --- | --- |
| Committer | [Eduardo Lopes (@e-Lopes)](https://github.com/e-Lopes) |
| Reviewer | [Eduardo Lopes (@e-Lopes)](https://github.com/e-Lopes) |
| Approver | [Eduardo Lopes (@e-Lopes)](https://github.com/e-Lopes) |

Contributions from other people must be reviewed before they are merged. The
maintainer account used for repository and signing access is required to use
multi-factor authentication.

## Privacy

PDF documents are processed locally. The application does not transfer user
documents or usage telemetry. It only contacts GitHub when checking for or
downloading an application update. See the complete
[Privacy Policy](PRIVACY.md).

## Reporting concerns

Security or signing concerns may be reported through the project's
[Issues page](https://github.com/e-Lopes/chess-book-diagram-extractor/issues).
