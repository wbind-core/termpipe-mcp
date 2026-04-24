class Bus:
    def pub(self, topic, data):
        print(f"[DUMMY BUS PUB] {topic}: {data}")
    def sub(self, topic):
        print(f"[DUMMY BUS SUB] Listening on {topic}")
        import time
        while True:
            time.sleep(1)
            yield None
