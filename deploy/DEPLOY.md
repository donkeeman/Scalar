# Oracle Cloud 배포 가이드

Oracle Cloud E2 Micro + DuckDNS + Caddy로 Scalar를 배포하는 절차.

## 1. 사전 준비

- Oracle Cloud E2 Micro 인스턴스 (Ubuntu 22.04)
- DuckDNS 도메인 (예: `scalar.duckdns.org`)
- GitHub App private key (`.pem` 파일)
- Groq API 키

## 2. 인스턴스 세팅

```bash
# 패키지 업데이트
sudo apt update && sudo apt upgrade -y

# 기본 도구
sudo apt install -y git curl debian-keyring debian-archive-keyring apt-transport-https

# uv 설치
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 3. 방화벽 설정 (Oracle Cloud 콘솔 + ufw)

Oracle Cloud 콘솔에서 VCN → Security Lists → 80/443 포트 ingress 허용.

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 4. DuckDNS 자동 업데이트

```bash
mkdir ~/duckdns && cd ~/duckdns
cat > duck.sh << 'EOF'
echo url="https://www.duckdns.org/update?domains=scalar&token=YOUR_TOKEN&ip=" | curl -k -o ~/duckdns/duck.log -K -
EOF
chmod 700 duck.sh
# crontab에 등록
(crontab -l ; echo "*/5 * * * * ~/duckdns/duck.sh >/dev/null 2>&1") | crontab -
```

## 5. Scalar 배포

```bash
git clone https://github.com/donkeeman/Scalar.git ~/Scalar
cd ~/Scalar

# .env 파일 생성
cat > .env << 'EOF'
GITHUB_APP_ID=YOUR_APP_ID
GITHUB_PRIVATE_KEY_PATH=/home/ubuntu/Scalar/scalar-agent.pem
LLM_BACKEND=groq
GROQ_API_KEY=YOUR_GROQ_KEY
GROQ_MODEL=qwen/qwen3-32b
EOF

# private key 업로드 (로컬에서 scp)
# scp scalar-agent.pem ubuntu@SERVER_IP:~/Scalar/

# 의존성 설치
uv sync
```

## 6. systemd 서비스 등록

```bash
sudo cp deploy/scalar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scalar
sudo systemctl start scalar
sudo systemctl status scalar
```

로그 확인:
```bash
sudo journalctl -u scalar -f
```

## 7. Caddy 설치 & 설정

```bash
# Caddy 설치
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# Caddyfile 설정
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
# 도메인 수정 필요: scalar.duckdns.org → 실제 도메인
sudo systemctl reload caddy
```

## 8. GitHub App webhook URL 업데이트

GitHub App 설정에서 webhook URL을 다음으로 변경:
```
https://scalar.duckdns.org/webhook
```

## 9. 검증

```bash
curl https://scalar.duckdns.org/
# {"status":"ok","message":"Scalar Code Review Bot"}
```

테스트 PR을 열어서 리뷰가 달리는지 확인.

## 문제 해결

- **서비스가 안 올라옴**: `sudo journalctl -u scalar -n 50`
- **Caddy HTTPS 실패**: DuckDNS가 서버 IP를 가리키는지 확인
- **webhook 반응 없음**: Oracle Cloud 방화벽, ufw, GitHub App URL 순서로 체크
