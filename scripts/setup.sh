#!/bin/bash
# Setup script for Echolia Backend

set -e

echo "🚀 Setting up Echolia Backend..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your credentials:"
    echo "   - TURSO_ORG_URL"
    echo "   - TURSO_AUTH_TOKEN"
    echo "   - JWT_SECRET (generate with: openssl rand -hex 32)"
    exit 1
fi

# Check if Turso CLI is installed
if ! command -v turso &> /dev/null; then
    echo "⚠️  Turso CLI not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install tursodatabase/tap/turso
    else
        curl -sSfL https://get.tur.so/install.sh | bash
    fi
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Prerequisites check passed!"
echo ""
echo "🔨 Building Docker containers..."
docker-compose build

echo ""
echo "✨ Setup complete!"
echo ""
echo "To start the server:"
echo "  docker-compose up -d"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop the server:"
echo "  docker-compose down"
