# anvyc Homebrew Formula 초안.
#
# 이 파일은 anvyc repo 내에서 관리하지만, 실제 brew tap 사용을 위해서는
# `16bitdo/homebrew-anvyc` repo 의 `Formula/anvyc.rb` 로 옮겨야 한다.
#
# release artifact 생성 후 sha256 값을 docs/homebrew-publishing.md 절차로 갱신.

class Anvyc < Formula
  include Language::Python::Virtualenv

  desc "여러 장치에서 개발 도구 설정을 안전하게 백업/비교/복원/동기화하는 macOS CLI"
  homepage "https://github.com/16bitdo/anvyc"
  url "https://github.com/16bitdo/anvyc/releases/download/v0.6.2/anvyc-0.6.2.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256_FROM_RELEASE"
  license "MIT"

  depends_on "python@3.13"

  # Python 의존성 — pyproject.toml 의 dependencies 와 동기화.
  # url + sha256 은 https://pypi.org/project/<pkg>/<version>/#files 의 sdist 항목 또는
  # `pip download <pkg>==<ver> --no-deps --no-binary=:all: -d /tmp/dl` 로 산출.

  resource "typer" do
    url "https://files.pythonhosted.org/packages/source/t/typer/typer-0.12.5.tar.gz"
    sha256 "REPLACE_WITH_TYPER_SDIST_SHA256"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/source/r/rich/rich-13.7.1.tar.gz"
    sha256 "REPLACE_WITH_RICH_SDIST_SHA256"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.6.4.tar.gz"
    sha256 "REPLACE_WITH_PYDANTIC_SDIST_SHA256"
  end

  resource "pathspec" do
    url "https://files.pythonhosted.org/packages/source/p/pathspec/pathspec-0.12.1.tar.gz"
    sha256 "REPLACE_WITH_PATHSPEC_SDIST_SHA256"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/PyYAML-6.0.1.tar.gz"
    sha256 "REPLACE_WITH_PYYAML_SDIST_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "anvyc v#{version}", shell_output("#{bin}/anvyc --version")
  end
end
