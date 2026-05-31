from minio import Minio

def test_minio(port):
    print(f"Testing port {port}...")
    try:
        client = Minio(
            f"89.167.72.254:{port}" if port else "89.167.72.254",
            access_key="admin",
            secret_key="password123",
            secure=False
        )
        # Try to list buckets to verify connection
        buckets = client.list_buckets()
        print("Success! Buckets:")
        for b in buckets:
            print("-", b.name)
    except Exception as e:
        print("Failed:", e)

test_minio(None)
test_minio(9000)
test_minio(9001)
