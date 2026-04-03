# Reference
<details><summary><code>client.<a href="src/concrete/client.py">get_health</a>() -> HealthStatus</code></summary>
<dl>
<dd>

#### 🔌 Usage

<dl>
<dd>

<dl>
<dd>

```python
from concrete import ConcreteApi
from concrete.environment import ConcreteApiEnvironment

client = ConcreteApi(
    environment=ConcreteApiEnvironment.DEFAULT,
)

client.get_health()

```
</dd>
</dl>
</dd>
</dl>

#### ⚙️ Parameters

<dl>
<dd>

<dl>
<dd>

**request_options:** `typing.Optional[RequestOptions]` — Request-specific configuration.
    
</dd>
</dl>
</dd>
</dl>


</dd>
</dl>
</details>

<details><summary><code>client.<a href="src/concrete/client.py">upload_file</a>(...) -> UploadResponse</code></summary>
<dl>
<dd>

#### 🔌 Usage

<dl>
<dd>

<dl>
<dd>

```python
from concrete import ConcreteApi
from concrete.environment import ConcreteApiEnvironment

client = ConcreteApi(
    environment=ConcreteApiEnvironment.DEFAULT,
)

client.upload_file(
    file="example_file",
)

```
</dd>
</dl>
</dd>
</dl>

#### ⚙️ Parameters

<dl>
<dd>

<dl>
<dd>

**file:** `typing.Optional[core.File]` — The file to upload (PDF, TXT, DOCX, etc.)
    
</dd>
</dl>

<dl>
<dd>

**metadata:** `typing.Optional[str]` — Optional JSON metadata associated with the file
    
</dd>
</dl>

<dl>
<dd>

**request_options:** `typing.Optional[RequestOptions]` — Request-specific configuration.
    
</dd>
</dl>
</dd>
</dl>


</dd>
</dl>
</details>

<details><summary><code>client.<a href="src/concrete/client.py">start_vector_update</a>() -> VectorUpdateResponse</code></summary>
<dl>
<dd>

#### 🔌 Usage

<dl>
<dd>

<dl>
<dd>

```python
from concrete import ConcreteApi
from concrete.environment import ConcreteApiEnvironment

client = ConcreteApi(
    environment=ConcreteApiEnvironment.DEFAULT,
)

client.start_vector_update()

```
</dd>
</dl>
</dd>
</dl>

#### ⚙️ Parameters

<dl>
<dd>

<dl>
<dd>

**request_options:** `typing.Optional[RequestOptions]` — Request-specific configuration.
    
</dd>
</dl>
</dd>
</dl>


</dd>
</dl>
</details>

